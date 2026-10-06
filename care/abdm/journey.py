import time
import uuid

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import NotFound

USER_TOKEN_CACHE_KEY = "abdm:abha:refresh_token:{abha_number}"


class Journey:
    """
    Server-side state of one ABHA journey at the desk.

    Holds the txnId and the patient's user tokens so they never reach the
    browser; the frontend only carries the opaque journey id.
    """

    def __init__(self, journey_id: str, user_id: int, data: dict | None = None):
        self.id = journey_id
        self.user_id = user_id
        self.data = data or {}

    @staticmethod
    def _key(journey_id: str) -> str:
        return f"abdm:journey:{journey_id}"

    @classmethod
    def start(cls, user) -> "Journey":
        return cls(str(uuid.uuid4()), user.id)

    @classmethod
    def load(cls, journey_id, user) -> "Journey":
        stored = cache.get(cls._key(str(journey_id)))
        # Another user's journey is reported as missing rather than forbidden
        if not stored or stored["user_id"] != user.id:
            raise NotFound("ABHA session expired. Start again.")
        return cls(str(journey_id), stored["user_id"], stored["data"])

    @classmethod
    def load_or_start(cls, journey_id, user) -> "Journey":
        if journey_id:
            return cls.load(journey_id, user)
        return cls.start(user)

    def save(self):
        cache.set(
            self._key(self.id),
            {"user_id": self.user_id, "data": self.data},
            settings.ABDM_JOURNEY_TTL_SECONDS,
        )

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value

    def set_user_token(self, token: str, expires_in: int | None):
        self["x_token"] = token
        self["x_token_expires_at"] = time.time() + int(expires_in or 0)

    @property
    def x_token(self) -> str | None:
        if self["x_token"] and time.time() < (self["x_token_expires_at"] or 0):
            return self["x_token"]
        return None


def remember_refresh_token(abha_number: str, refresh_token: str, expires_in):
    if abha_number and refresh_token and expires_in:
        cache.set(
            USER_TOKEN_CACHE_KEY.format(abha_number=abha_number),
            refresh_token,
            int(expires_in),
        )


def recall_refresh_token(abha_number: str) -> str | None:
    return cache.get(USER_TOKEN_CACHE_KEY.format(abha_number=abha_number))


def forget_refresh_token(abha_number: str):
    cache.delete(USER_TOKEN_CACHE_KEY.format(abha_number=abha_number))
