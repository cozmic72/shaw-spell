#!/usr/bin/env python3
"""
Test server for Shaw-Spell Dictionary web frontend.

Usage:
    ./src/tools/test_site.py [port]

Default port: 8000
"""

import sys
import os
from pathlib import Path
from http.server import HTTPServer, CGIHTTPRequestHandler


class RootCGIHTTPRequestHandler(CGIHTTPRequestHandler):
    """CGI handler that serves CGI scripts from the document root."""

    def is_cgi(self):
        """Check if path should be handled as CGI."""
        if self.path.endswith('.cgi') or '/index.cgi' in self.path:
            # Treat .cgi files in root as CGI scripts
            self.cgi_info = '', self.path.lstrip('/')
            return True
        return False


# Get paths
project_root = Path(__file__).parent.parent.parent
site_dir = project_root / 'build' / 'site'

# Check if site is built
if not site_dir.exists():
    print("Error: Site not built yet!")
    print("Run 'make site' first.")
    sys.exit(1)

# Get port
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# Change to site directory and run server
os.chdir(site_dir)
print(f"Starting server at http://localhost:{port}/index.cgi")
print("Press Ctrl+C to stop")

server = HTTPServer(('', port), RootCGIHTTPRequestHandler)
server.serve_forever()
