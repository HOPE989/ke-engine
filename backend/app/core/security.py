import base64
import hashlib
import hmac
import os

from app.core.config import get_settings

_HASH_ALGORITHM = "pbkdf2_sha256"


def get_password_hash(password: str) -> str:
    settings = get_settings()
    salt = os.urandom(16)
    digest = _hash_password(password, salt, settings.password_hash_iterations)
    return "$".join(
        [
            _HASH_ALGORITHM,
            str(settings.password_hash_iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        algorithm, iterations, salt, expected_digest = hashed_password.split("$", 3)
        if algorithm != _HASH_ALGORITHM:
            return False

        salt_bytes = base64.b64decode(salt.encode("ascii"))
        expected_digest_bytes = base64.b64decode(expected_digest.encode("ascii"))
        actual_digest = _hash_password(plain_password, salt_bytes, int(iterations))
        return hmac.compare_digest(actual_digest, expected_digest_bytes)
    except (ValueError, TypeError):
        return False


def _hash_password(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )

