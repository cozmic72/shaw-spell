#!/usr/bin/env python3
"""
Local server for the Shaw-Spell web frontend — the only one that works.

Despite the "test" in its name this is not an optional convenience, and
`python3 -m http.server --cgi` is NOT an alternative. Stock http.server
executes CGI only for scripts under /cgi-bin/; this site's index.cgi sits
at the docroot ROOT, so http.server serves it as a plain file and every
page 404s or returns the unexecuted template. RootCGIHTTPRequestHandler
below exists to override exactly that.

It also spawns the suggestd daemon the CGI talks to, pointed at the built
site's data and hunspell dirs, with the socket under the current build
tree — so no /opt/shaw-spell/ and no root are needed.

Usage:
    ./src/tools/test_site.py [port]

Default port: 8000
"""

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from http.server import HTTPServer, CGIHTTPRequestHandler


DAEMON_START_TIMEOUT_SEC = 60


class RootCGIHTTPRequestHandler(CGIHTTPRequestHandler):
    """CGI handler that serves CGI scripts from the document root."""

    def is_cgi(self):
        if self.path.endswith('.cgi') or '/index.cgi' in self.path:
            self.cgi_info = '', self.path.lstrip('/')
            return True
        return False


def wait_for_socket(path, timeout):
    """Block until the daemon's socket accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    s.connect(path)
                return True
            except OSError:
                pass
        time.sleep(0.1)
    return False


def start_daemon(project_root, site_dir):
    """Spawn suggestd as a child process using the repo's daemon source and
    the built data/hunspell dirs. Returns (process, socket_path)."""
    daemon_py = project_root / 'src' / 'site-daemon' / 'suggestd.py'
    hunspell_dir = site_dir / 'hunspell'
    data_dir = site_dir / 'site-data'

    for required, label in [
        (daemon_py, 'daemon source'),
        (hunspell_dir, 'hunspell dictionaries'),
        (data_dir, 'site-data JSONs'),
    ]:
        if not required.exists():
            print(f"Error: missing {label}: {required}")
            print("Run 'make site' first.")
            sys.exit(1)

    # Keep the socket inside the build tree to avoid clashing with a
    # production /run/shaw-spell/suggestd.sock if one exists on this host.
    socket_path = site_dir / '.suggestd.sock'
    if socket_path.exists():
        socket_path.unlink()

    # Tee the daemon's logs to both the terminal (for convenience) and a
    # file under the build tree (for post-hoc inspection of stalls etc.).
    daemon_log = site_dir / '.suggestd.log'
    print(f"Starting suggestd daemon (socket: {socket_path})")
    print(f"  daemon log: {daemon_log}")
    log_fh = open(daemon_log, 'a', buffering=1, encoding='utf-8')
    log_fh.write(f'\n=== suggestd started at {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')
    # Use a process pipe so we can tee: spawn `tee` to duplicate stderr.
    proc = subprocess.Popen(
        [
            sys.executable, '-u', str(daemon_py),
            '--socket', str(socket_path),
            '--hunspell-dir', str(hunspell_dir),
            '--data-dir', str(data_dir),
        ],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )

    def _stop_daemon():
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        log_fh.close()
    atexit.register(_stop_daemon)

    if not wait_for_socket(str(socket_path), DAEMON_START_TIMEOUT_SEC):
        print("Error: suggestd failed to start within "
              f"{DAEMON_START_TIMEOUT_SEC}s")
        _stop_daemon()
        sys.exit(1)

    print("suggestd ready.")
    return proc, socket_path


def main():
    project_root = Path(__file__).parent.parent.parent
    site_dir = project_root / 'build' / 'site'

    if not site_dir.exists():
        print("Error: Site not built yet!")
        print("Run 'make site' first.")
        sys.exit(1)

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    _, socket_path = start_daemon(project_root, site_dir)

    # Point the CGI at our local socket. CGIHTTPRequestHandler passes the
    # parent's environment through to scripts.
    os.environ['SHAW_SPELL_SUGGEST_SOCKET'] = str(socket_path)

    os.chdir(site_dir)
    print(f"Starting web server at http://localhost:{port}/index.cgi")
    print("Press Ctrl+C to stop")

    server = HTTPServer(('', port), RootCGIHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Shutting down.")


if __name__ == '__main__':
    main()
