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

# Login throttle: after this many failures for a handle within the window, reject
# further attempts until the window lapses. Persisted in SQLite because editor.cgi
# runs as a fresh process per request — in-memory state would never accumulate.
LOGIN_MAX_FAILURES = 8
LOGIN_WINDOW_SECONDS = 300

# A throwaway hash the miss path verifies against, so a nonexistent handle costs
# the same PBKDF2 work as a real one — no timing oracle for handle existence.
_DUMMY_HASH = None

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
            CREATE TABLE IF NOT EXISTS login_failures (
                handle TEXT NOT NULL,
                ts INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_login_failures ON login_failures(handle, ts);
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


def drop_user(handle, path=None):
    """Delete a user (sessions cascade). Returns True if a row was removed."""
    conn = _connect(path)
    try:
        cur = conn.execute("DELETE FROM users WHERE handle = ?", (handle,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_password(handle, password, path=None):
    """Reset an existing user's password. Raises if the handle is unknown."""
    conn = _connect(path)
    try:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE handle = ?",
                           (_hash_password(password), handle))
        conn.commit()
        if cur.rowcount == 0:
            raise AuthError(f"no such user: {handle}")
    finally:
        conn.close()


def authenticate(handle, password, path=None):
    """Return the user_id on a correct handle+password, else None. Bad handle
    and bad password are indistinguishable — same 401 AND same time cost (the
    miss path verifies a dummy hash), so neither value nor timing leaks handle
    existence. Rejects (as None) once a handle is rate-limited."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _hash_password(secrets.token_hex(16))
    conn = _connect(path)
    try:
        if _is_rate_limited(conn, handle):
            _verify_password(password, _DUMMY_HASH)  # keep the cost uniform
            return None
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE handle = ? LIMIT 1",
            (handle,)).fetchone()
        encoded = row[1] if row is not None else _DUMMY_HASH
        ok = _verify_password(password, encoded)
        if row is None or not ok:
            _record_login_failure(conn, handle)
            return None
        _clear_login_failures(conn, handle)
        return row[0]
    finally:
        conn.close()


def _is_rate_limited(conn, handle):
    cutoff = int(time.time()) - LOGIN_WINDOW_SECONDS
    conn.execute("DELETE FROM login_failures WHERE ts < ?", (cutoff,))
    conn.commit()
    (n,) = conn.execute(
        "SELECT COUNT(*) FROM login_failures WHERE handle = ? AND ts >= ?",
        (handle, cutoff)).fetchone()
    return n >= LOGIN_MAX_FAILURES


def _record_login_failure(conn, handle):
    conn.execute("INSERT INTO login_failures (handle, ts) VALUES (?, ?)",
                 (handle, int(time.time())))
    conn.commit()


def _clear_login_failures(conn, handle):
    conn.execute("DELETE FROM login_failures WHERE handle = ?", (handle,))
    conn.commit()


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
    # --password-stdin (anywhere in argv): read the password from stdin's first
    # line instead of getpass — pipe it from a password manager without paste
    # mangling. Strips a single trailing newline only.
    stdin_pw = "--password-stdin" in argv
    argv = [a for a in argv if a != "--password-stdin"]

    if not argv:
        sys.stderr.write(
            "usage: authstore.py --create-user <handle> | --drop-user <handle> | "
            "--set-password <handle> | --list-users | --delete-sessions <handle>\n"
            "  add --password-stdin to read the password from stdin (no prompt)\n")
        return 2

    def read_password(handle):
        if stdin_pw:
            # Strip a single trailing newline (LF or CRLF) only — a bare \n rstrip
            # would leave the \r of a CRLF baked into the password.
            line = sys.stdin.readline()
            if line.endswith("\r\n"):
                pw = line[:-2]
            elif line.endswith("\n"):
                pw = line[:-1]
            else:
                pw = line
            if not pw:
                sys.stderr.write("password must not be empty\n"); return None
            return pw
        pw1 = getpass.getpass(f"Password for {handle}: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            sys.stderr.write("passwords do not match\n"); return None
        if not pw1:
            sys.stderr.write("password must not be empty\n"); return None
        return pw1

    cmd = argv[0]
    if cmd == "--create-user":
        if len(argv) != 2:
            sys.stderr.write("usage: authstore.py --create-user <handle>\n")
            return 2
        pw = read_password(argv[1])
        if pw is None:
            return 1
        user_id = create_user(argv[1], pw)
        sys.stdout.write(f"created user {argv[1]} (id {user_id})\n")
        return 0

    if cmd == "--drop-user":
        if len(argv) != 2:
            sys.stderr.write("usage: authstore.py --drop-user <handle>\n")
            return 2
        if drop_user(argv[1]):
            sys.stdout.write(f"dropped user {argv[1]}\n"); return 0
        sys.stderr.write(f"no such user: {argv[1]}\n"); return 1

    if cmd == "--set-password":
        if len(argv) != 2:
            sys.stderr.write("usage: authstore.py --set-password <handle>\n")
            return 2
        pw = read_password(argv[1])
        if pw is None:
            return 1
        set_password(argv[1], pw)
        sys.stdout.write(f"password updated for {argv[1]}\n")
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
