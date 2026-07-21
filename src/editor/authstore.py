#!/usr/bin/env python3
"""
Auth store for the editorial editor — SQLite-backed users + sessions.

Sign-in only: accounts are provisioned by the owner via the getpass CLI
(`--create-user`), there is no self-serve signup, roles, or password reset.
A verified session identifies the human whose handle becomes the patch author
(the security boundary lives in editor.cgi; this module only stores and checks
credentials). Passwords are PBKDF2-HMAC-SHA256, verified in constant time.

Design ported from shave's Swift AuthStore; reimplemented in Python stdlib
(no third-party deps).
"""

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import sys
import time

PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16
PBKDF2_HASH_BYTES = 32
HASH_SCHEME = "pbkdf2_sha256"

SESSION_TTL_SECONDS = 30 * 24 * 3600
SESSION_TOKEN_BYTES = 32

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "auth", "users.sqlite")


class AuthError(Exception):
    """A precondition the caller must handle (e.g. duplicate handle). Storage
    errors propagate as sqlite3.Error — neither is swallowed."""


def db_path():
    return os.environ.get("SHAW_SPELL_AUTH_DB", DEFAULT_DB_PATH)


def _connect(path=None):
    path = path or db_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(path=None):
    conn = _connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                handle TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---- password hashing (PBKDF2-HMAC-SHA256) ----

def _hash_password(password, iterations=PBKDF2_ITERATIONS):
    salt = os.urandom(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 iterations, dklen=PBKDF2_HASH_BYTES)
    return "{}${}${}${}".format(
        HASH_SCHEME, iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"))


def _verify_password(password, encoded):
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != HASH_SCHEME:
        raise AuthError("unrecognised password hash format")
    iterations = int(parts[1])
    if iterations < 1:
        raise AuthError("invalid PBKDF2 iteration count")
    salt = base64.b64decode(parts[2])
    expected = base64.b64decode(parts[3])
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                   iterations, dklen=len(expected))
    return hmac.compare_digest(expected, computed)


# ---- users ----

def create_user(handle, password, path=None):
    conn = _connect(path)
    try:
        try:
            cur = conn.execute(
                "INSERT INTO users (handle, password_hash, created_at) VALUES (?, ?, ?)",
                (handle, _hash_password(password), int(time.time())))
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise AuthError(f"handle already exists: {handle}") from exc
    finally:
        conn.close()


def authenticate(handle, password, path=None):
    """Return the user_id on a correct handle+password, else None. Bad handle
    and bad password are indistinguishable to the caller (no enumeration
    oracle)."""
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE handle = ? LIMIT 1",
            (handle,)).fetchone()
        if row is None:
            return None
        user_id, encoded = row
        return user_id if _verify_password(password, encoded) else None
    finally:
        conn.close()


def handle_for_user(user_id, path=None):
    conn = _connect(path)
    try:
        row = conn.execute("SELECT handle FROM users WHERE id = ? LIMIT 1",
                           (user_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ---- sessions ----

def create_session(user_id, path=None):
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    now = int(time.time())
    conn = _connect(path)
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now + SESSION_TTL_SECONDS, now))
        conn.commit()
        return token
    finally:
        conn.close()


def user_for_session(token, path=None):
    """Return (user_id, handle) for a live session, else None. Expired rows are
    reaped on lookup (fail closed — an expired token is never honoured)."""
    if not token:
        return None
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT s.user_id, s.expires_at, u.handle "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? LIMIT 1", (token,)).fetchone()
        if row is None:
            return None
        user_id, expires_at, handle = row
        if expires_at <= int(time.time()):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return (user_id, handle)
    finally:
        conn.close()


def delete_session(token, path=None):
    if not token:
        return
    conn = _connect(path)
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def delete_sessions_for_handle(handle, path=None):
    conn = _connect(path)
    try:
        cur = conn.execute(
            "DELETE FROM sessions WHERE user_id = "
            "(SELECT id FROM users WHERE handle = ?)", (handle,))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def list_users(path=None):
    conn = _connect(path)
    try:
        return conn.execute(
            "SELECT handle, created_at FROM users ORDER BY LOWER(handle)").fetchall()
    finally:
        conn.close()


# ---- CLI (owner provisioning) ----

def _cli(argv):
    import getpass

    migrate()
    if not argv:
        sys.stderr.write("usage: authstore.py --create-user <handle> | "
                         "--list-users | --delete-sessions <handle>\n")
        return 2

    cmd = argv[0]
    if cmd == "--create-user":
        if len(argv) != 2:
            sys.stderr.write("usage: authstore.py --create-user <handle>\n")
            return 2
        handle = argv[1]
        pw1 = getpass.getpass(f"Password for {handle}: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            sys.stderr.write("passwords do not match\n")
            return 1
        if not pw1:
            sys.stderr.write("password must not be empty\n")
            return 1
        user_id = create_user(handle, pw1)
        sys.stdout.write(f"created user {handle} (id {user_id})\n")
        return 0

    if cmd == "--list-users":
        for handle, created_at in list_users():
            sys.stdout.write(f"{handle}\t{created_at}\n")
        return 0

    if cmd == "--delete-sessions":
        if len(argv) != 2:
            sys.stderr.write("usage: authstore.py --delete-sessions <handle>\n")
            return 2
        n = delete_sessions_for_handle(argv[1])
        sys.stdout.write(f"deleted {n} session(s) for {argv[1]}\n")
        return 0

    sys.stderr.write(f"unknown command: {cmd}\n")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
