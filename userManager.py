"""Password verification, server-enforced roles, and authenticator-app TOTP."""

import base64
import functools
import hashlib
import hmac
import secrets
import struct
import time
from flask import abort, g, session
from db import get_db


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 260000
    ).hex()
    return f"pbkdf2_sha256$260000${salt}${digest}"


def verify_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(rounds)
        ).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def totp(secret, step=None):
    step = int(time.time() // 30) if step is None else step
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f'{(struct.unpack(">I",digest[offset:offset+4])[0]&0x7fffffff)%1000000:06d}'


def verify_totp(secret, code, last=-1):
    now = int(time.time() // 30)
    for step in range(now - 1, now + 2):
        if step > last and hmac.compare_digest(totp(secret, step), str(code)):
            return step
    return None


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def public_user(row):
    return {
        k: row[k] for k in ("id", "username", "name", "email", "role", "active")
    } | {"two_factor": bool(row["totp_secret"])}


def require(*roles):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            user = (
                get_db()
                .execute("SELECT * FROM users WHERE id=?", (session.get("uid"),))
                .fetchone()
            )
            if (
                not user
                or not user["active"]
                or session.get("version") != user["version"]
            ):
                session.clear()
                abort(401, description="Please sign in again.")
            if roles and user["role"] not in roles:
                abort(403, description="Your role cannot perform this action.")
            g.user = user
            return fn(*args, **kwargs)

        return wrapped

    return decorate
