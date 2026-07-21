"""Shared password hashing helpers for SchoolOS authentication flows."""

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Generate a bcrypt password hash for a plain-text password."""
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plain-text password against a stored hash."""
    return _pwd_context.verify(plain_password, password_hash)
