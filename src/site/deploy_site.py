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
    fonts_src = project_root / 'src' / 'fonts'
    output_path = project_root / output_dir
    data_dir = project_root / 'build' / 'site-data'

    # Ensure source directory exists
    if not site_src.exists():
        print(f"Error: Site source directory not found: {site_src}")
        return 1

    # Ensure data directory exists
    if not data_dir.exists():
        print(f"Error: Site data directory not found: {data_dir}")
        print("Run src/site/build_site_index.py first to build indexes")
        return 1

    # Create output directory (remove if exists)
    if output_path.exists():
        print(f"Removing existing output directory: {output_path}")
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Deploying Shaw Dict web frontend v{version}")
    print(f"  Source: {site_src}")
    print(f"  Output: {output_path}")
    print()

    # Track statistics
    stats = {
        'html': 0,
        'css': 0,
        'js': 0,
        'cgi': 0,
        'other': 0
    }

    # Files/dirs to exclude from deployment
    exclude_patterns = {'__pycache__', '.DS_Store', 'build_site_index.py', 'deploy_site.py'}

    # Load welcome fragments for interpolation
    def load_and_escape_template(filename, default=''):
        """Load a template file and escape it for Python string interpolation."""
        template_file = site_src / 'templates' / filename
        if template_file.exists():
            with open(template_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Replace version placeholder
                content = content.replace('$VERSION$', version)
                # Escape for Python string literal: escape backslashes and quotes
                content = content.replace('\\', '\\\\').replace("'", "\\'")
                # Remove newlines to keep it as a single line
                content = content.replace('\n', ' ')
                return content
        return default

    # Load both Latin and Shavian versions
    welcome_top_content = load_and_escape_template('welcome-top.html', '<p>Welcome!</p>')
    welcome_bottom_content = load_and_escape_template('welcome-bottom.html', '')
    welcome_top_shavian_content = load_and_escape_template('welcome-top-shavian.html', welcome_top_content)
    welcome_bottom_shavian_content = load_and_escape_template('welcome-bottom-shavian.html', welcome_bottom_content)

    # Walk through site source directory
    for source_file in site_src.rglob('*'):
        # Skip excluded files
        if source_file.name in exclude_patterns:
            continue

        if source_file.is_file():
            # Calculate relative path
            rel_path = source_file.relative_to(site_src)
            dest_file = output_path / rel_path

            # Create parent directory if needed
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            # Process based on file type
            if source_file.suffix in ['.html', '.css', '.js']:
                # Read file
                with open(source_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Replace version placeholders
                content = content.replace('$VERSION$', version)

                # Replace font URL placeholder (especially in CSS)
                content = content.replace('{{FONT_URL}}', font_url)

                # Write to output
                with open(dest_file, 'w', encoding='utf-8') as f:
                    f.write(content)

                # Update stats
                if source_file.suffix == '.html':
                    stats['html'] += 1
                elif source_file.suffix == '.css':
                    stats['css'] += 1
                elif source_file.suffix == '.js':
                    stats['js'] += 1

                print(f"  ✓ {rel_path}")

            elif source_file.suffix in ['.py', '.cgi'] or source_file.name.endswith('.cgi'):
                # CGI scripts - process and make executable
                with open(source_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Replace placeholders
                content = content.replace('$VERSION$', version)
                content = content.replace('{{FONT_URL}}', font_url)
                content = content.replace('{{WELCOME_TOP}}', welcome_top_content)
                content = content.replace('{{WELCOME_BOTTOM}}', welcome_bottom_content)
                content = content.replace('{{WELCOME_TOP_SHAVIAN}}', welcome_top_shavian_content)
                content = content.replace('{{WELCOME_BOTTOM_SHAVIAN}}', welcome_bottom_shavian_content)

                # Write to output
                with open(dest_file, 'w', encoding='utf-8') as f:
                    f.write(content)

                # Make executable
                os.chmod(dest_file, 0o755)
                stats['cgi'] += 1
                print(f"  ✓ {rel_path} (executable)")

            else:
                # Copy other files as-is
                shutil.copy2(source_file, dest_file)
                stats['other'] += 1

    # Copy fonts to output
    print()
    print("Copying fonts...")
    fonts_output = output_path / 'fonts'
    fonts_output.mkdir(exist_ok=True)

    for font_file in fonts_src.glob('*.otf'):
        dest = fonts_output / font_file.name
        shutil.copy2(font_file, dest)
        print(f"  ✓ fonts/{font_file.name}")
        stats['other'] += 1

    # Copy data files to output
    print()
    print("Copying dictionary data files...")
    data_output = output_path / 'data'
    data_output.mkdir(exist_ok=True)

    for data_file in data_dir.glob('*.json'):
        dest = data_output / data_file.name
        shutil.copy2(data_file, dest)
        print(f"  ✓ data/{data_file.name}")
        stats['other'] += 1

    print()
    print(f"Deployed {stats['html']} HTML files, {stats['css']} CSS files, "
          f"{stats['js']} JS files, {stats['cgi']} CGI scripts, {stats['other']} other files")

    # Write version to file for tracking
    version_file = output_path / '.version'
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(version)
    print(f"  ✓ Version written to {version_file.name}")

    print()
    print("✅ Deployment complete!")
    print()
    print(f"To test locally:")
    print(f"  cd {output_path} && python3 -m http.server --cgi 8000")

    return 0


def read_version_file():
    """Read version from current-version file."""
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
