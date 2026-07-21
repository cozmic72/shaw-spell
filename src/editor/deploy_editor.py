#!/usr/bin/env python3
"""
Deploy script for the Shaw-Spell editorial editor.

Stages the editor into build/editor/, mirroring src/site/deploy_site.py. The
tarball ships CODE only, plus install.sh (the server-side installer that copies
each piece into place). Three destinations + writable state:

  build/editor/                     -> web tier /var/www/shaw-spell/editor
    editor.cgi, index.cgi (755)     the CGI (index.cgi is a copy so DirectoryIndex
                                    resolves /editor/), the browser UI, and the
    editor.js, editor.css           Shavian webfont under fonts/ so editor.css's
    fonts/BernieSansBetaVF.woff2    relative url('fonts/...') resolves.
    authstore.py                    sits BESIDE the cgi (the cgi adds its own dir
                                    to sys.path) — inside the docroot, not above it.

  build/editor/editor-daemon/       -> /opt/shaw-spell (PROJECT_ROOT). The src/
    src/editor/*.py                 level is preserved from the repo ON PURPOSE:
    src/tools/*.py                  basis.py computes PROJECT_ROOT as
    shaw-spell-editord.service      parent.parent.parent, so tools/basis.py must
                                    sit THREE dirs below PROJECT_ROOT — i.e. at
                                    src/tools/, exactly as in the repo. Flatten
                                    the src/ level and PROJECT_ROOT lands on /opt
                                    instead of /opt/shaw-spell and every basis
                                    path 404s. editord adds HERE + HERE.parent/
                                    tools to sys.path, so editor/ and tools/ are
                                    siblings under src/.

  build/editor/basis/               -> /opt/shaw-spell (paths preserved). The
    external/readlex/readlex.json   ~317MB read-only basis the daemon reads. Staged
    data/supplement-...json         under basis/ mirroring the repo tree so
    data/definitions-shavian-*.json install.sh copies it straight into $OPT_ROOT and
    external/frequency-words/...     every PROJECT_ROOT-relative path resolves. This
                                    IS the payload — the tarball ships the expensive
                                    artifacts so the server needs no rebuild.

  build/editor/install.sh (755)     the server-side installer: copies the web
                                    tier + daemon + basis into place, creates the
                                    writable state under /var/lib/shaw-spell, and
                                    prints the manual steps (Apache SetEnv, seed user).

Writable state (auth DB + patch stores) lives under /var/lib/shaw-spell, owned
by the service user — created by install.sh, NOT staged here.

Usage:
    python deploy_editor.py [--version VERSION]
"""

import os
import shutil
import sys
from pathlib import Path

# editord's own module graph, split by source dir. The daemon runs from
# editor-daemon/src/editor/ and imports the tools from editor-daemon/src/tools/,
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

# The read-only basis the daemon reads, repo-relative. Staged under basis/ with
# paths preserved so install.sh drops them straight into $OPT_ROOT. The first
# four are required (daemon won't start without them); the freq corpus is
# optional — basis.py soft-fails to freq-0 when it's absent.
BASIS_REQUIRED = [
    'external/readlex/readlex.json',
    'data/supplement-combined-filtered.json',
    'data/definitions-shavian-gb.json',
    'data/definitions-shavian-us.json',
]
BASIS_OPTIONAL = [
    'external/frequency-words/content/2018/en/en_full.txt',
]


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

    # authstore.py sits BESIDE the cgi in the editor dir (the cgi adds its own
    # dir to sys.path). It stays inside /var/www/shaw-spell/editor/, not in the
    # shared site docroot. The user DB is a separate concern — mutable state
    # under /var/lib/shaw-spell, pointed to by SHAW_SPELL_AUTH_DB (see deploy notes).
    shutil.copy2(editor_src / 'authstore.py', output_path / 'authstore.py')
    print(f"  ✓ authstore.py (beside the cgi)")

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
    # The src/ level is preserved: basis.py's PROJECT_ROOT = parent.parent.parent,
    # so src/tools/basis.py must sit three dirs below /opt/shaw-spell. See docstring.
    print()
    print("Copying editor daemon...")
    daemon_output = output_path / 'editor-daemon'
    daemon_editor = daemon_output / 'src' / 'editor'
    daemon_tools = daemon_output / 'src' / 'tools'
    daemon_editor.mkdir(parents=True, exist_ok=True)
    daemon_tools.mkdir(parents=True, exist_ok=True)

    for name in EDITOR_MODULES:
        src = editor_src / name
        if not src.exists():
            print(f"Error: daemon module missing: {src}")
            return 1
        shutil.copy2(src, daemon_editor / name)
        print(f"  ✓ editor-daemon/src/editor/{name}")

    for name in TOOLS_MODULES:
        src = tools_src / name
        if not src.exists():
            print(f"Error: tools module missing: {src}")
            return 1
        shutil.copy2(src, daemon_tools / name)
        print(f"  ✓ editor-daemon/src/tools/{name}")

    service = editor_src / 'shaw-spell-editord.service'
    shutil.copy2(service, daemon_output / service.name)
    print(f"  ✓ editor-daemon/{service.name}")

    # --- read-only basis (-> /opt/shaw-spell, paths preserved) ---
    # THE payload: the ~317MB of expensive artifacts, so the server rebuilds
    # nothing. Staged under basis/<repo-relative-path>; install.sh copies the
    # tree into $OPT_ROOT. Required inputs fail the build if missing; the freq
    # corpus is skipped-with-notice (basis.py soft-fails to freq-0).
    print()
    print("Copying read-only basis...")
    basis_output = output_path / 'basis'
    for rel in BASIS_REQUIRED:
        src = project_root / rel
        if not src.exists():
            print(f"Error: required basis input missing: {src}")
            return 1
        dest = basis_output / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"  ✓ basis/{rel}  ({src.stat().st_size >> 20} MB)")
    for rel in BASIS_OPTIONAL:
        src = project_root / rel
        if not src.exists():
            print(f"  – basis/{rel} absent — skipped (freq sort disabled)")
            continue
        dest = basis_output / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"  ✓ basis/{rel}  ({src.stat().st_size >> 20} MB)")

    # --- server-side installer at the tarball root (owner runs sudo ./install.sh) ---
    # Writable state under /var/lib is created by the installer, not staged here.
    print()
    install_src = editor_src / 'install.sh.template'
    if not install_src.exists():
        print(f"Error: installer template missing: {install_src}")
        return 1
    install_dest = output_path / 'install.sh'
    shutil.copy2(install_src, install_dest)
    os.chmod(install_dest, 0o755)
    print(f"  ✓ install.sh (executable)")

    # Version marker (mirrors deploy_site.py).
    version_file = output_path / '.version'
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(version)
    print()
    print(f"  ✓ Version {version} written to {version_file.name}")

    print()
    print("✅ Editor staged. Tarball root carries install.sh (sudo ./install.sh on")
    print("   the server) plus the full basis under basis/ — the server rebuilds")
    print("   nothing. Writable state is created under /var/lib/shaw-spell.")
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
