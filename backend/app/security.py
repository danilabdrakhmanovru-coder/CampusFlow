import hashlib
import hmac
import secrets

COOKIE = "campusflow_session"


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"{salt}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    return hmac.compare_digest(password_hash(password, stored.split(":")[0]), stored)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
