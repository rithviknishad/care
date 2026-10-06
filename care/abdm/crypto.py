import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_der_public_key
from django.conf import settings
from django.core.cache import cache

from care.abdm.client import abha_json

CERTIFICATE_CACHE_KEY = "abdm:abha:public_certificate"


def _oaep_sha1():
    return padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA1()),  # noqa: S303
        algorithm=hashes.SHA1(),  # noqa: S303
        label=None,
    )


# Keyed by the `encryptionAlgorithm` the certificate endpoint publishes
PADDINGS = {
    "RSA/ECB/OAEPWithSHA-1AndMGF1Padding": _oaep_sha1,
    "RSA/ECB/PKCS1Padding": padding.PKCS1v15,
}


class UnsupportedEncryptionAlgorithmError(Exception):
    pass


def get_certificate() -> dict:
    certificate = cache.get(CERTIFICATE_CACHE_KEY)
    if certificate:
        return certificate
    data = abha_json("GET", "/v3/profile/public/certificate")
    certificate = {
        "public_key": data["publicKey"],
        "algorithm": data["encryptionAlgorithm"],
    }
    cache.set(CERTIFICATE_CACHE_KEY, certificate, settings.ABDM_CERTIFICATE_TTL_SECONDS)
    return certificate


def invalidate_certificate():
    cache.delete(CERTIFICATE_CACHE_KEY)


def encrypt(value: str) -> str:
    certificate = get_certificate()
    padding_factory = PADDINGS.get(certificate["algorithm"])
    if padding_factory is None:
        raise UnsupportedEncryptionAlgorithmError(certificate["algorithm"])
    public_key = load_der_public_key(base64.b64decode(certificate["public_key"]))
    ciphertext = public_key.encrypt(value.encode(), padding_factory())
    return base64.b64encode(ciphertext).decode()
