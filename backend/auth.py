
from werkzeug.security import generate_password_hash, check_password_hash


def hash_password(password):
    """Convert a plain-text password into a secure hash."""
    return generate_password_hash(password)


def verify_password(password, password_hash):
    """Check whether a password matches its stored hash."""
    return check_password_hash(password_hash, password)
