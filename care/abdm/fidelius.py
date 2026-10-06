"""
Encryption of health records for the HIU, as ABDM's Fidelius scheme does it.

ABDM's key material is BouncyCastle's "curve25519": the Weierstrass form of
Curve25519, with public keys sent as raw uncompressed points (0x04 || x || y).
The scalar multiplication runs on the Montgomery form through X25519, and
coordinates are mapped between the two forms with x = u + A/3.
"""

import base64
import os
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.utils import timezone

from care.abdm.client import abdm_time

P = 2**255 - 19
MONTGOMERY_A = 486662


def _inverse(value: int) -> int:
    return pow(value, P - 2, P)


A_THIRD = MONTGOMERY_A * _inverse(3) % P
WEIERSTRASS_A = (3 - MONTGOMERY_A**2) * _inverse(3) % P
WEIERSTRASS_B = (2 * MONTGOMERY_A**3 - 9 * MONTGOMERY_A) * _inverse(27) % P
POINT_LENGTH = 65
NONCE_LENGTH = 32
# BouncyCastle's curve25519 base point and group order
BASE_Y = 0x20AE19A1B8A086B4E01EDD2C7748D14C923D4D7E6D7C61B229E9C5A27ECED3D9
ORDER = 2**252 + 0x14DEF9DEA2F79CD65812631A5CF5D3ED
COFACTOR = 8


def _der(tag: int, content: bytes) -> bytes:
    length = len(content)
    if length < 0x80:  # noqa: PLR2004
        encoded = bytes([length])
    else:
        raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
        encoded = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + encoded + content


def _der_int(value: int) -> bytes:
    return _der(0x02, value.to_bytes(value.bit_length() // 8 + 1, "big"))


def _spki_prefix() -> bytes:
    """
    The fixed head of an X.509 SubjectPublicKeyInfo for a curve25519 key, with the
    curve's parameters written out explicitly as BouncyCastle (and so Fidelius) does.
    """
    ec_public_key = bytes.fromhex("06072a8648ce3d0201")
    prime_field = bytes.fromhex("06072a8648ce3d0101")
    base = (
        b"\x04" + ((9 + A_THIRD) % P).to_bytes(32, "big") + BASE_Y.to_bytes(32, "big")
    )
    parameters = _der(
        0x30,
        _der_int(1)
        + _der(0x30, prime_field + _der_int(P))
        + _der(
            0x30,
            _der(0x04, WEIERSTRASS_A.to_bytes(32, "big"))
            + _der(0x04, WEIERSTRASS_B.to_bytes(32, "big")),
        )
        + _der(0x04, base)
        + _der_int(ORDER)
        + _der_int(COFACTOR),
    )
    algorithm = _der(0x30, ec_public_key + parameters)
    placeholder = b"\x00" * POINT_LENGTH
    spki = _der(0x30, algorithm + _der(0x03, b"\x00" + placeholder))
    return spki[:-POINT_LENGTH]


SPKI_PREFIX = _spki_prefix()


class KeyMaterialError(ValueError):
    pass


def _sqrt(value: int) -> int:
    # p = 5 mod 8, so a square root is one of two candidates
    root = pow(value, (P + 3) // 8, P)
    if root * root % P != value % P:
        root = root * pow(2, (P - 1) // 4, P) % P
    if root * root % P != value % P:
        msg = "Not a point on curve25519"
        raise KeyMaterialError(msg)
    return root


def _point(key: bytes) -> bytes:
    """The raw uncompressed point, whether sent bare or inside an X.509 SubjectPublicKeyInfo."""
    if len(key) == POINT_LENGTH and key[0] == 0x04:  # noqa: PLR2004
        return key
    if len(key) > POINT_LENGTH and key[0] == 0x30 and key[-POINT_LENGTH] == 0x04:  # noqa: PLR2004
        return key[-POINT_LENGTH:]
    msg = "Unrecognised public key encoding"
    raise KeyMaterialError(msg)


def _on_curve(x: int, y: int) -> bool:
    return (y * y - (x**3 + WEIERSTRASS_A * x + WEIERSTRASS_B)) % P == 0


def _weierstrass_to_x25519(point: bytes) -> X25519PublicKey:
    x = int.from_bytes(point[1:33], "big")
    y = int.from_bytes(point[33:], "big")
    if not _on_curve(x, y):
        msg = "Public key is not on curve25519"
        raise KeyMaterialError(msg)
    u = (x - A_THIRD) % P
    return X25519PublicKey.from_public_bytes(u.to_bytes(32, "little"))


def _x25519_to_weierstrass(public_key: X25519PublicKey) -> bytes:
    u = int.from_bytes(public_key.public_bytes_raw(), "little")
    x = (u + A_THIRD) % P
    y = _sqrt((x**3 + WEIERSTRASS_A * x + WEIERSTRASS_B) % P)
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def _session(shared_x: bytes, sender_nonce: bytes, receiver_nonce: bytes):
    xored = bytes(a ^ b for a, b in zip(sender_nonce, receiver_nonce, strict=True))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=xored[:20], info=None).derive(
        shared_x
    )
    return AESGCM(key), xored[-12:]


def _decode_nonce(nonce: str) -> bytes:
    try:
        value = base64.b64decode(nonce, validate=True)
    except ValueError as e:
        msg = "Nonce is not base64"
        raise KeyMaterialError(msg) from e
    if len(value) != NONCE_LENGTH:
        msg = f"Nonce must be {NONCE_LENGTH} bytes"
        raise KeyMaterialError(msg)
    return value


def _peer(key_material: dict) -> tuple[X25519PublicKey, bytes, bytes]:
    """The other side's public key, its nonce, and the encoding it sent the key in."""
    if str(key_material.get("curve", "")).lower() != "curve25519":
        msg = f"Unsupported curve {key_material.get('curve')}"
        raise KeyMaterialError(msg)
    try:
        raw_key = base64.b64decode(key_material["dhPublicKey"]["keyValue"])
    except (KeyError, TypeError, ValueError) as e:
        msg = "Key material carries no usable public key"
        raise KeyMaterialError(msg) from e
    return (
        _weierstrass_to_x25519(_point(raw_key)),
        _decode_nonce(key_material.get("nonce", "")),
        raw_key,
    )


def _shared_session(private_key, own_nonce, peer_key, peer_nonce):
    shared_u = int.from_bytes(private_key.exchange(peer_key), "little")
    shared_x = ((shared_u + A_THIRD) % P).to_bytes(32, "big")
    return _session(shared_x, own_nonce, peer_nonce)


def _key_material(private_key, nonce: bytes) -> dict:
    point = _x25519_to_weierstrass(private_key.public_key())
    return {
        "cryptoAlg": "ECDH",
        "curve": "Curve25519",
        "dhPublicKey": {
            "expiry": abdm_time(timezone.now() + timedelta(days=1)),
            "parameters": "Curve25519/32byte random key",
            # X.509 even to a peer that sent a bare point: the ABHA app reads nothing else
            "keyValue": base64.b64encode(SPKI_PREFIX + point).decode(),
        },
        "nonce": base64.b64encode(nonce).decode(),
    }


class Encryptor:
    """One key pair and nonce per transfer, which is what gives forward secrecy."""

    def __init__(self, requester_key_material: dict):
        requester_key, requester_nonce, _ = _peer(requester_key_material)
        self._private_key = X25519PrivateKey.generate()
        self._nonce = os.urandom(NONCE_LENGTH)
        self._cipher, self._iv = _shared_session(
            self._private_key, self._nonce, requester_key, requester_nonce
        )

    def encrypt(self, data: str) -> str:
        return base64.b64encode(
            self._cipher.encrypt(self._iv, data.encode(), None)
        ).decode()

    def key_material(self) -> dict:
        return _key_material(self._private_key, self._nonce)


class Decryptor:
    """The requester's side: a key pair offered in the request, kept until the records arrive."""

    def __init__(self, secret: dict | None = None):
        if secret:
            self._private_key = X25519PrivateKey.from_private_bytes(
                base64.b64decode(secret["private_key"])
            )
            self._nonce = base64.b64decode(secret["nonce"])
        else:
            self._private_key = X25519PrivateKey.generate()
            self._nonce = os.urandom(NONCE_LENGTH)

    def secret(self) -> dict:
        return {
            "private_key": base64.b64encode(
                self._private_key.private_bytes_raw()
            ).decode(),
            "nonce": base64.b64encode(self._nonce).decode(),
        }

    def key_material(self) -> dict:
        return _key_material(self._private_key, self._nonce)

    def decrypt(self, content: str, sender_key_material: dict) -> str:
        sender_key, sender_nonce, _ = _peer(sender_key_material)
        cipher, iv = _shared_session(
            self._private_key, self._nonce, sender_key, sender_nonce
        )
        try:
            return cipher.decrypt(iv, base64.b64decode(content), None).decode()
        except (InvalidTag, ValueError) as e:
            msg = "Content does not decrypt with the key material sent beside it"
            raise KeyMaterialError(msg) from e
