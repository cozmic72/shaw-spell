#!/usr/bin/env python3
"""
Regression test: editord must shut down PROMPTLY on SIGTERM.

The bug (fixed): main()'s signal handler called server.shutdown() inline. That
handler runs on the MAIN thread — the same thread running serve_forever() — and
BaseServer.shutdown() blocks until serve_forever() returns and must be called
from a DIFFERENT thread, so the inline call deadlocked. serve_forever() never
returned, the process never exited, and systemd SIGKILLed it after
TimeoutStopSec (~90s) on every `systemctl restart`.

This test spawns the real daemon on a TEMP socket (never the production/dev
socket), waits for it to come up, sends SIGTERM, and asserts it exits well
within a few seconds with the socket unlinked. A regression that reintroduces
the inline shutdown() deadlocks and this test fails on the exit timeout.

Standalone (no test framework): exits 0 on pass, non-zero on fail.
"""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DAEMON = PROJECT_ROOT / "src" / "editor" / "editord.py"

# The daemon loads a large basis (~6s); allow generous startup, but the SIGTERM
# exit itself must be FAST. A deadlocked daemon would hang until systemd's ~90s
# TimeoutStopSec — this bound is far below that yet far above a clean exit.
STARTUP_TIMEOUT_SEC = 120
SHUTDOWN_TIMEOUT_SEC = 10


def _wait_for_socket(sock_path, proc, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"daemon exited during startup rc={proc.returncode}")
        if os.path.exists(sock_path):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect(sock_path)
                return
            except OSError:
                pass
        time.sleep(0.1)
    raise RuntimeError(f"daemon did not come up within {timeout}s")


def test_sigterm_exits_promptly():
    tmpdir = tempfile.mkdtemp(prefix="editord-shutdown-test-")
    sock_path = os.path.join(tmpdir, "editord.sock")
    log_path = os.path.join(tmpdir, "editord.log")
    log_fh = open(log_path, "w+", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-u", str(DAEMON), "--socket", sock_path],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_socket(sock_path, proc, STARTUP_TIMEOUT_SEC)

        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        try:
            rc = proc.wait(timeout=SHUTDOWN_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            log_fh.seek(0)
            raise AssertionError(
                f"editord did not exit within {SHUTDOWN_TIMEOUT_SEC}s of SIGTERM "
                f"— shutdown DEADLOCK (inline server.shutdown() on the "
                f"serve_forever thread?). log tail:\n{log_fh.read()[-1000:]}"
            )
        elapsed = time.monotonic() - started

        assert rc == 0, f"editord exited non-zero on SIGTERM: rc={rc}"
        assert not os.path.exists(sock_path), (
            f"socket not unlinked after shutdown: {sock_path}"
        )
        print(f"PASS: SIGTERM -> clean exit rc={rc} in {elapsed:.2f}s, socket unlinked")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log_fh.close()


if __name__ == "__main__":
    test_sigterm_exits_promptly()
