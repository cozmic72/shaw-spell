#!/usr/bin/env python3
"""
Deploy script for Shaw Dict web frontend.
Copies src/site/ directory to build/site/, replacing $VERSION$ placeholders
in HTML, CSS, and JavaScript files.

Usage:
    python deploy_site.py [--version VERSION]
"""

import sys
import os
import shutil
from pathlib import Path


def deploy(version, font_url='fonts', output_dir='build/site'):
    """Deploy site files with variable interpolation to output directory."""
    project_root = Path(__file__).parent.parent.parent
    site_src = project_root / 'src' / 'site'
    site_daemon_src = project_root / 'src' / 'site-daemon'
    fonts_src = project_root / 'src' / 'fonts'
    output_path = project_root / output_dir
    # Prebuilt committed artifacts from the data repo — built by `make site`
    # on the build machine, shipped to the server via git. Never built here.
    data_dir = project_root / 'data' / 'site-data'
    hunspell_dir = project_root / 'data' / 'hunspell'

    if not site_src.exists():
        print(f"Error: Site source directory not found: {site_src}")
        return 1

    if not data_dir.exists():
        print(f"Error: Site data directory not found: {data_dir}")
        print("Run 'make site' on the build machine and pull the data repo")
        return 1

    if not hunspell_dir.exists():
        print(f"Error: Hunspell directory not found: {hunspell_dir}")
        print("Run 'make site' on the build machine and pull the data repo")
        return 1

    if output_path.exists():
        print(f"Removing existing output directory: {output_path}")
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Deploying Shaw Dict web frontend v{version}")
    print(f"  Source: {site_src}")
    print(f"  Output: {output_path}")
    print()

    stats = {
        'html': 0,
        'css': 0,
        'js': 0,
        'cgi': 0,
        'other': 0
    }

    exclude_patterns = {'__pycache__', '.DS_Store', 'build_site_index.py', 'deploy_site.py'}

    def load_and_escape_template(filename, default=''):
        """Load a template file and escape it for interpolation into a Python
        string literal in the CGI (backslashes/quotes escaped, newlines
        flattened so it stays a single line)."""
        template_file = site_src / 'templates' / filename
        if template_file.exists():
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
                content = content.replace('$VERSION$', version)
                content = content.replace('\\', '\\\\').replace("'", "\\'")
                content = content.replace('\n', ' ')
                return content
        return default

    welcome_top_content = load_and_escape_template('welcome-top.html', '<p>Welcome!</p>')
    welcome_bottom_content = load_and_escape_template('welcome-bottom.html', '')
    welcome_top_shavian_content = load_and_escape_template('welcome-top-shavian.html', welcome_top_content)
    welcome_bottom_shavian_content = load_and_escape_template('welcome-bottom-shavian.html', welcome_bottom_content)

    for source_file in site_src.rglob('*'):
        if source_file.name in exclude_patterns:
            continue

        if source_file.is_file():
            rel_path = source_file.relative_to(site_src)
            dest_file = output_path / rel_path

            dest_file.parent.mkdir(parents=True, exist_ok=True)

            if source_file.suffix in ['.html', '.css', '.js']:
                with open(source_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                content = content.replace('$VERSION$', version)
                content = content.replace('{{FONT_URL}}', font_url)

                with open(dest_file, 'w', encoding='utf-8') as f:
                    f.write(content)

                if source_file.suffix == '.html':
                    stats['html'] += 1
                elif source_file.suffix == '.css':
                    stats['css'] += 1
                elif source_file.suffix == '.js':
                    stats['js'] += 1

                print(f"  ✓ {rel_path}")

            elif source_file.suffix in ['.py', '.cgi'] or source_file.name.endswith('.cgi'):
                with open(source_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                content = content.replace('$VERSION$', version)
                content = content.replace('{{FONT_URL}}', font_url)
                content = content.replace('{{WELCOME_TOP}}', welcome_top_content)
                content = content.replace('{{WELCOME_BOTTOM}}', welcome_bottom_content)
                content = content.replace('{{WELCOME_TOP_SHAVIAN}}', welcome_top_shavian_content)
                content = content.replace('{{WELCOME_BOTTOM_SHAVIAN}}', welcome_bottom_shavian_content)

                with open(dest_file, 'w', encoding='utf-8') as f:
                    f.write(content)

                os.chmod(dest_file, 0o755)
                stats['cgi'] += 1
                print(f"  ✓ {rel_path} (executable)")

            else:
                shutil.copy2(source_file, dest_file)
                stats['other'] += 1

    print()
    print("Copying fonts...")
    fonts_output = output_path / 'fonts'
    fonts_output.mkdir(exist_ok=True)

    for pattern in ('*.otf', '*.ttf', '*.woff', '*.woff2'):
        for font_file in fonts_src.glob(pattern):
            dest = fonts_output / font_file.name
            shutil.copy2(font_file, dest)
            print(f"  ✓ fonts/{font_file.name}")
            stats['other'] += 1

    # Copy dictionary JSONs. These are read by the suggest daemon, not by
    # the CGI — ops installs this directory at /opt/shaw-spell/site-data/
    # (matching the --data-dir path in the systemd unit).
    print()
    print("Copying dictionary data files...")
    data_output = output_path / 'site-data'
    data_output.mkdir(exist_ok=True)

    for data_file in data_dir.glob('*.json'):
        dest = data_output / data_file.name
        shutil.copy2(data_file, dest)
        print(f"  ✓ site-data/{data_file.name}")
        stats['other'] += 1

    # Copy spelling-suggestion daemon sources. These live alongside the
    # site but aren't served directly — ops installs them under
    # /opt/shaw-spell/site-daemon/ and enables the systemd unit.
    if site_daemon_src.exists():
        print()
        print("Copying suggest daemon...")
        daemon_output = output_path / 'site-daemon'
        daemon_output.mkdir(exist_ok=True)
        for src_file in site_daemon_src.rglob('*'):
            if src_file.is_file() and src_file.name != '.DS_Store':
                rel = src_file.relative_to(site_daemon_src)
                dest = daemon_output / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dest)
                print(f"  ✓ site-daemon/{rel}")
                stats['other'] += 1
    else:
        print()
        print(f"Warning: {site_daemon_src} not found — skipping daemon bundle")

    # Copy Hunspell dictionaries. The daemon needs these at runtime; ops
    # installs them under /opt/shaw-spell/hunspell/ (matches the path in
    # the systemd unit). Stage them into build/site so install-site copies
    # them into place in one pass.
    print()
    print("Copying Hunspell dictionaries...")
    hunspell_output = output_path / 'hunspell'
    hunspell_output.mkdir(exist_ok=True)
    for hunspell_file in hunspell_dir.iterdir():
        if hunspell_file.suffix in ('.aff', '.dic') and hunspell_file.is_file():
            dest = hunspell_output / hunspell_file.name
            shutil.copy2(hunspell_file, dest)
            print(f"  ✓ hunspell/{hunspell_file.name}")
            stats['other'] += 1

    print()
    print(f"Deployed {stats['html']} HTML files, {stats['css']} CSS files, "
          f"{stats['js']} JS files, {stats['cgi']} CGI scripts, {stats['other']} other files")

    version_file = output_path / '.version'
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(version)
    print(f"  ✓ Version written to {version_file.name}")

    print()
    print("✅ Deployment complete!")
    print()
    print(f"To test locally:")
    print(f"  cd {output_path} && python3 -m http.server --cgi 8000")
    print()
    print("To deploy on the server: run  make install-site  (copies this staged")
    print("  tree into place and enables the suggestd daemon).")

    return 0


def read_version_file():
    project_root = Path(__file__).parent.parent.parent
    version_file = project_root / 'current-version'

    try:
        with open(version_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error: Could not read version from {version_file}")
        sys.exit(1)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Deploy Shaw Dict web frontend with version replacement')
    parser.add_argument('-v', '--version', help='Version number (default: read from current-version file)')
    parser.add_argument('-f', '--font-url', default='fonts', help='Font URL/directory (default: fonts)')
    parser.add_argument('-o', '--output-dir', default='build/site', help='Output directory (default: build/site)')

    args = parser.parse_args()

    version = args.version or read_version_file()

    return deploy(version, args.font_url, args.output_dir)


if __name__ == '__main__':
    sys.exit(main())
