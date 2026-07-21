#!/usr/bin/env python3
"""
Deploy script for the Shaw-Spell editorial editor.

Stages the editor into build/editor/, mirroring src/site/deploy_site.py. The
tree splits into two install targets (see build-rules/editor.mk for the ops
steps):

  build/editor/                     -> Apache docroot /var/www/shaw-spell/editor
    editor.cgi, index.cgi (755)     the CGI (index.cgi is a copy so DirectoryIndex
                                    resolves /editor/), the browser UI, and the
    editor.js, editor.css           Shavian webfont under fonts/ so editor.css's
    fonts/BernieSansBetaVF.woff2    relative url('fonts/...') resolves.
  build/editor/authstore.py         -> /var/www/shaw-spell/authstore.py — one
                                    level ABOVE the docroot, because editor.cgi
                                    imports it via sys.path=dirname(dirname(cgi)).
                                    Not web-served.

  build/editor/editor-daemon/       -> /opt/shaw-spell (PROJECT_ROOT). editord's
    editor/*.py                     module graph is flat across two sibling dirs
    tools/*.py                      exactly as in the repo (editord adds HERE and
    shaw-spell-editord.service      HERE.parent/tools to sys.path), so basis.py's
                                    parent.parent.parent lands on /opt/shaw-spell
                                    and every data/ path resolves there.

The tarball ships CODE only. The daemon's read-only basis inputs
(external/readlex/readlex.json, data/supplement-combined-filtered.json,
data/definitions-shavian-{gb,us}.json, and the optional frequency corpus) plus
the runtime-writable data/patches/ and data/auth/ are synced by ops under
/opt/shaw-spell — they are NOT baked in. Empty writable seed dirs are staged.

Usage:
    python deploy_editor.py [--version VERSION]
"""

import os
import shutil
import sys
from pathlib import Path

# editord's own module graph, split by source dir. The daemon runs from
# editor-daemon/editor/ and imports the tools modules from editor-daemon/tools/,
# exactly as editord.py's sys.path (HERE, HERE.parent/tools) prescribes.
EDITOR_MODULES = [
    'editord.py',
    'overlay.py',
    'patchstore.py',
    'definitions.py',
    'definition_patches.py',
]
TOOLS_MODULES = [
    'basis.py',
    'dialect_mergers.py',
    'apply_frequency_data.py',
    'spelling_variants.py',
]

# The web tier served by Apache at the docroot.
WEB_FILES = ['editor.cgi', 'editor.js', 'editor.css']

FONT = 'BernieSansBetaVF.woff2'


def deploy(version, output_dir='build/editor'):
    project_root = Path(__file__).resolve().parent.parent.parent
    editor_src = project_root / 'src' / 'editor'
    editor_site_src = editor_src / 'site'
    tools_src = project_root / 'src' / 'tools'
    fonts_src = project_root / 'src' / 'fonts'
    output_path = project_root / output_dir

    if not editor_site_src.exists():
        print(f"Error: editor site source not found: {editor_site_src}")
        return 1

    if output_path.exists():
        print(f"Removing existing output directory: {output_path}")
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Deploying Shaw-Spell editorial editor v{version}")
    print(f"  Source: {editor_src}")
    print(f"  Output: {output_path}")
    print()

    # --- web tier (docroot root) ---
    for name in WEB_FILES:
        src = editor_site_src / name
        if not src.exists():
            print(f"Error: web file missing: {src}")
            return 1
        dest = output_path / name
        shutil.copy2(src, dest)
        if name.endswith('.cgi'):
            os.chmod(dest, 0o755)
            print(f"  ✓ {name} (executable)")
        else:
            print(f"  ✓ {name}")

    # index.cgi is a copy of editor.cgi so Apache's DirectoryIndex resolves
    # /editor/. editor.js posts to location.pathname + "?api=...", so the
    # filename is never hardcoded — the copy is self-sufficient.
    index_cgi = output_path / 'index.cgi'
    shutil.copy2(editor_site_src / 'editor.cgi', index_cgi)
    os.chmod(index_cgi, 0o755)
    print(f"  ✓ index.cgi (copy of editor.cgi, executable)")

    # authstore lives ONE level above the docroot: editor.cgi imports it via
    # sys.path = dirname(dirname(__file__)). Staged at build/editor/authstore.py
    # -> extracts to /var/www/shaw-spell/authstore.py.
    shutil.copy2(editor_src / 'authstore.py', output_path / 'authstore.py')
    print(f"  ✓ authstore.py (docroot parent — CGI import target)")

    # --- Shavian webfont ---
    print()
    print("Copying Shavian webfont...")
    fonts_output = output_path / 'fonts'
    fonts_output.mkdir(exist_ok=True)
    font_src = fonts_src / FONT
    if not font_src.exists():
        print(f"Error: font missing: {font_src}")
        return 1
    shutil.copy2(font_src, fonts_output / FONT)
    print(f"  ✓ fonts/{FONT}")

    # --- daemon tree (-> /opt/shaw-spell) ---
    print()
    print("Copying editor daemon...")
    daemon_output = output_path / 'editor-daemon'
    daemon_editor = daemon_output / 'editor'
    daemon_tools = daemon_output / 'tools'
    daemon_editor.mkdir(parents=True, exist_ok=True)
    daemon_tools.mkdir(parents=True, exist_ok=True)

    for name in EDITOR_MODULES:
        src = editor_src / name
        if not src.exists():
            print(f"Error: daemon module missing: {src}")
            return 1
        shutil.copy2(src, daemon_editor / name)
        print(f"  ✓ editor-daemon/editor/{name}")

    for name in TOOLS_MODULES:
        src = tools_src / name
        if not src.exists():
            print(f"Error: tools module missing: {src}")
            return 1
        shutil.copy2(src, daemon_tools / name)
        print(f"  ✓ editor-daemon/tools/{name}")

    service = editor_src / 'shaw-spell-editord.service'
    shutil.copy2(service, daemon_output / service.name)
    print(f"  ✓ editor-daemon/{service.name}")

    # --- writable seed dirs (empty; ops makes them www-data-writable) ---
    print()
    print("Staging writable seed dirs...")
    for rel in ('data/patches', 'data/auth'):
        (output_path / 'editor-daemon' / rel).mkdir(parents=True, exist_ok=True)
        print(f"  ✓ editor-daemon/{rel}/ (empty, runtime-writable)")

    # Version marker (mirrors deploy_site.py).
    version_file = output_path / '.version'
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(version)
    print()
    print(f"  ✓ Version {version} written to {version_file.name}")

    print()
    print("✅ Editor staged.")
    print("   NOTE: the daemon's read-only basis inputs (external/readlex/,")
    print("   data/supplement-combined-filtered.json, data/definitions-shavian-*.json,")
    print("   optional frequency corpus) are synced by ops under /opt/shaw-spell,")
    print("   NOT bundled here. See editor-tarball deploy notes.")
    return 0


def read_version_file():
    project_root = Path(__file__).resolve().parent.parent.parent
    version_file = project_root / 'current-version'
    try:
        with open(version_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error: Could not read version from {version_file}")
        sys.exit(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Stage the Shaw-Spell editor into build/editor')
    parser.add_argument('-v', '--version', help='Version (default: read from current-version)')
    parser.add_argument('-o', '--output-dir', default='build/editor',
                        help='Output directory (default: build/editor)')
    args = parser.parse_args()

    version = args.version or read_version_file()
    return deploy(version, args.output_dir)


if __name__ == '__main__':
    sys.exit(main())
