"""Password hashing and username policy (pure functions)."""
import hashlib
import hmac
import secrets

ITERATIONS = 240_000


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, AttributeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(12))
