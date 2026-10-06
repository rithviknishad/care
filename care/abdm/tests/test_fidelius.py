import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.test import SimpleTestCase

from care.abdm import fidelius
from care.abdm.fidelius import (
    A_THIRD,
    MONTGOMERY_A,
    WEIERSTRASS_A,
    Decryptor,
    Encryptor,
    KeyMaterialError,
    P,
    _session,
)

# BouncyCastle's published curve25519 parameters, independent of our derivation
BC_A = 0x2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA984914A144
BC_B = 0x7B425ED097B425ED097B425ED097B425ED097B425ED097B4260B5E9C7710C864
BC_GX = 0x2AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD245A
BC_GY = 0x20AE19A1B8A086B4E01EDD2C7748D14C923D4D7E6D7C61B229E9C5A27ECED3D9
SPEC_SAMPLE_KEY = "BFN7KTdOT0jIAExG2A8Jg+01wMPWxptiGqwHRVvtiVEsUq2FR7P2UdqZxJyPJSeR6muai21iQhasNxnhh8I5M+g="


def _add(p1, p2):
    """Affine point addition on the Weierstrass curve, as an HIU's BouncyCastle would do."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        slope = (3 * x1 * x1 + WEIERSTRASS_A) * pow(2 * y1, P - 2, P) % P
    else:
        slope = (y2 - y1) * pow(x2 - x1, P - 2, P) % P
    x3 = (slope * slope - x1 - x2) % P
    return x3, (slope * (x1 - x3) - y1) % P


def _multiply(scalar, point):
    result = None
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _encode(point):
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def _decode(raw):
    return int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big")


class TestFidelius(SimpleTestCase):
    def test_parameters_match_bouncycastle(self):
        self.assertEqual(fidelius.WEIERSTRASS_A, BC_A)
        self.assertEqual(fidelius.WEIERSTRASS_B, BC_B)
        self.assertEqual((9 + A_THIRD) % P, BC_GX)
        self.assertEqual(MONTGOMERY_A, 486662)

    def test_spec_sample_key_is_accepted(self):
        Encryptor(
            {
                "curve": "curve25519",
                "dhPublicKey": {"keyValue": SPEC_SAMPLE_KEY},
                "nonce": base64.b64encode(os.urandom(32)).decode(),
            }
        )

    def test_hiu_decrypts_what_the_hip_encrypts(self):
        # The HIU side uses plain Weierstrass arithmetic with an unclamped scalar
        hiu_private = secrets.randbelow(2**252)
        hiu_public = _multiply(hiu_private, (BC_GX, BC_GY))
        hiu_nonce = os.urandom(32)

        encryptor = Encryptor(
            {
                "cryptoAlg": "ECDH",
                "curve": "Curve25519",
                "dhPublicKey": {"keyValue": base64.b64encode(_encode(hiu_public))},
                "nonce": base64.b64encode(hiu_nonce).decode(),
            }
        )
        bundle = '{"resourceType": "Bundle"}'
        content = encryptor.encrypt(bundle)
        material = encryptor.key_material()

        hip_public = _decode(
            base64.b64decode(material["dhPublicKey"]["keyValue"])[-65:]
        )
        shared_x = _multiply(hiu_private, hip_public)[0].to_bytes(32, "big")
        cipher, iv = _session(shared_x, hiu_nonce, base64.b64decode(material["nonce"]))
        self.assertIsInstance(cipher, AESGCM)
        plain = cipher.decrypt(iv, base64.b64decode(content), None)
        self.assertEqual(plain.decode(), bundle)

    def test_rejects_point_off_curve(self):
        bad = b"\x04" + (1).to_bytes(32, "big") + (1).to_bytes(32, "big")
        with self.assertRaises(KeyMaterialError):
            Encryptor(
                {
                    "curve": "curve25519",
                    "dhPublicKey": {"keyValue": base64.b64encode(bad).decode()},
                    "nonce": base64.b64encode(os.urandom(32)).decode(),
                }
            )

    def test_rejects_short_nonce(self):
        with self.assertRaises(KeyMaterialError):
            Encryptor(
                {
                    "curve": "curve25519",
                    "dhPublicKey": {"keyValue": SPEC_SAMPLE_KEY},
                    "nonce": base64.b64encode(b"short").decode(),
                }
            )


class TestDecryptor(SimpleTestCase):
    def _hip_encrypts(self, our_material, plain, wrap=lambda raw: raw):
        """An HIP with plain Weierstrass arithmetic, independent of our X25519 path."""
        hip_private = secrets.randbelow(2**252)
        hip_nonce = os.urandom(32)
        our_public = _decode(
            base64.b64decode(our_material["dhPublicKey"]["keyValue"])[-65:]
        )
        shared_x = _multiply(hip_private, our_public)[0].to_bytes(32, "big")
        cipher, iv = _session(
            shared_x, hip_nonce, base64.b64decode(our_material["nonce"])
        )
        content = base64.b64encode(cipher.encrypt(iv, plain.encode(), None)).decode()
        hip_point = _encode(_multiply(hip_private, (BC_GX, BC_GY)))
        return content, {
            "cryptoAlg": "ECDH",
            "curve": "Curve25519",
            "dhPublicKey": {"keyValue": base64.b64encode(wrap(hip_point)).decode()},
            "nonce": base64.b64encode(hip_nonce).decode(),
        }

    def test_decrypts_what_an_independent_hip_encrypts(self):
        decryptor = Decryptor()
        content, material = self._hip_encrypts(decryptor.key_material(), "{}")
        # The key survives being stored between the request and the push
        restored = Decryptor(decryptor.secret())
        self.assertEqual(restored.decrypt(content, material), "{}")

    def test_accepts_an_x509_wrapped_sender_key(self):
        decryptor = Decryptor()
        content, material = self._hip_encrypts(
            decryptor.key_material(),
            "{}",
            wrap=lambda raw: b"\x30" + b"\x00" * 10 + raw,
        )
        self.assertEqual(decryptor.decrypt(content, material), "{}")

    def test_round_trip_with_our_encryptor(self):
        decryptor = Decryptor()
        encryptor = Encryptor(decryptor.key_material())
        content = encryptor.encrypt('{"resourceType": "Bundle"}')
        self.assertEqual(
            decryptor.decrypt(content, encryptor.key_material()),
            '{"resourceType": "Bundle"}',
        )

    def test_refuses_content_for_another_key(self):
        content, material = self._hip_encrypts(Decryptor().key_material(), "{}")
        with self.assertRaises(KeyMaterialError):
            Decryptor().decrypt(content, material)
