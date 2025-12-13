#!/usr/bin/env python3
"""
Template interpolation script for dictionary files.

Replaces placeholders like {{KEY}} with values provided as arguments.
Special handling for {{DESCRIPTION}} which reads from a file.

Usage:
  interpolate_template.py <template> <output> KEY=value KEY=value ...
  interpolate_template.py <template> <output> DESCRIPTION=<file> KEY=value ...
"""

import sys

def interpolate_template(template_path, output_path, substitutions):
    """Read template, interpolate placeholders, and write output."""

    # Read template
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Perform substitutions
    for key, value in substitutions.items():
        placeholder = '{{' + key + '}}'
        content = content.replace(placeholder, value)

    # Write output
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <template> <output> KEY=value ...", file=sys.stderr)
        sys.exit(1)

    template_path = sys.argv[1]
    output_path = sys.argv[2]

    # Parse key=value arguments
    substitutions = {}
    for arg in sys.argv[3:]:
        if '=' not in arg:
            print(f"Error: Invalid argument '{arg}'. Expected KEY=value format.", file=sys.stderr)
            sys.exit(1)

        key, value = arg.split('=', 1)

        # Special handling: if key is DESCRIPTION and value looks like a file path, read it
        if key == 'DESCRIPTION' and '/' in value:
            try:
                with open(value, 'r', encoding='utf-8') as f:
                    value = f.read()
            except FileNotFoundError:
                print(f"Error: Description file '{value}' not found.", file=sys.stderr)
                sys.exit(1)

        substitutions[key] = value

    interpolate_template(template_path, output_path, substitutions)
