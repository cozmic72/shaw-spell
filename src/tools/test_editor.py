#!/usr/bin/env python3
"""
Test server for the Shaw-Spell editorial editor web frontend.

Mirrors test_site.py: spawns the editord daemon in the background on a socket
under the source tree, then serves src/editor/site/ over CGI. The CGI is
configured via environment to use that local socket — no /run/shaw-spell/ or
root needed for local testing.

The HTTP server binds 0.0.0.0 so the editor is reachable from other devices on
the LAN. NOTE: this exposes a WRITE endpoint (the patch op mutates the store) on
the LAN with no authentication — auth is deferred to Phase 2. The editord daemon
itself stays behind a local Unix socket; only this HTTP front is on the network.

Usage:
    ./src/tools/test_editor.py [port]

Default port: 8010
"""

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, CGIHTTPRequestHandler


DAEMON_START_TIMEOUT_SEC = 120
DEFAULT_PORT = 8010


class RootCGIHTTPRequestHandler(CGIHTTPRequestHandler):
    """CGI handler that serves .cgi scripts from the document root."""

    def is_cgi(self):
        # / serves editor.cgi directly (no directory-listing hop), PRESERVING the
        # query string (?api=login etc. — dropping it broke the login POST to /).
        path, _, query = self.path.partition('?')
        if path in ('/', ''):
            self.path = '/editor.cgi' + (('?' + query) if query else '')
        if self.path.split('?', 1)[0].endswith('.cgi'):
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
    """Spawn editord as a child process on a socket inside the source tree.
    Returns (process, socket_path)."""
    daemon_py = project_root / 'src' / 'editor' / 'editord.py'
    if not daemon_py.exists():
        print(f"Error: missing daemon source: {daemon_py}")
        sys.exit(1)

    # Keep the socket inside the source tree to avoid clashing with a production
    # /run/shaw-spell/editord.sock if one exists on this host.
    socket_path = site_dir / '.editord.sock'
    if socket_path.exists():
        socket_path.unlink()

    daemon_log = site_dir / '.editord.log'
    print(f"Starting editord daemon (socket: {socket_path})")
    print(f"  daemon log: {daemon_log}")
    log_fh = open(daemon_log, 'a', buffering=1, encoding='utf-8')
    log_fh.write(f'\n=== editord started at {time.strftime("%Y-%m-%d %H:%M:%S")} ===\n')
    proc = subprocess.Popen(
        [
            sys.executable, '-u', str(daemon_py),
            '--socket', str(socket_path),
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
        print(f"Error: editord failed to start within {DAEMON_START_TIMEOUT_SEC}s")
        print(f"  see {daemon_log}")
        _stop_daemon()
        sys.exit(1)

    print("editord ready.")
    return proc, socket_path


def ensure_font(project_root, site_dir):
    """The Shavian webfont is loaded from fonts/ under the doc root, matching the
    production site. Symlink the source fonts there so Shavian renders instead of
    falling back to a sans-serif (see src/editor/README.md)."""
    fonts_link = site_dir / 'fonts'
    if not fonts_link.exists():
        fonts_link.symlink_to(project_root / 'src' / 'fonts')


def check_keyboard(site_dir):
    """`make shaw-keys` stages both keyboard assets into this docroot: the
    widget dir and the shared modal wrapper. Fail here rather than let the page
    404 on an import the browser reports only in its console."""
    for asset in ('shaw-keys/shaw-keys.js', 'shaw-keys-modal.js'):
        if not (site_dir / asset).exists():
            print(f"Error: {site_dir / asset} is missing — run 'make shaw-keys'")
            sys.exit(1)


def main():
    project_root = Path(__file__).parent.parent.parent
    site_dir = project_root / 'src' / 'editor' / 'site'

    if not (site_dir / 'editor.cgi').exists():
        print(f"Error: editor site not found at {site_dir}")
        sys.exit(1)

    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT

    ensure_font(project_root, site_dir)
    check_keyboard(site_dir)
    _, socket_path = start_daemon(project_root, site_dir)

    # Point the CGI at our local socket. CGIHTTPRequestHandler passes the
    # parent's environment through to scripts.
    os.environ['SHAW_SPELL_EDITOR_SOCKET'] = str(socket_path)

    os.chdir(site_dir)
    print(f"Starting editor at http://localhost:{port}/editor.cgi")
    print(f"  bound to 0.0.0.0:{port} — reachable on the LAN")
    print("  WARNING: this is an unauthenticated WRITE endpoint (auth is Phase 2)")
    print("Press Ctrl+C to stop")

    # Threaded so a phone's parallel asset fetches don't serialize on the LAN's
    # first (uncached) load. HTTP/1.0 kept — CGI streams without Content-Length.
    server = ThreadingHTTPServer(('0.0.0.0', port), RootCGIHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Shutting down.")


if __name__ == '__main__':
    main()
