#!/usr/bin/env python3
"""
Template interpolation script for dictionary files.

Replaces placeholders like $KEY$ with values provided as arguments.
If a value refers to an existing file, reads the file contents.

Usage:
  interpolate_template.py <template> <output> KEY=value KEY=value ...
  interpolate_template.py <template> <output> DESCRIPTION=file.html KEY=value ...
"""

import sys
import os.path

def interpolate_template(template_path, output_path, substitutions):
    """Read template, interpolate placeholders, and write output."""

    # Read template
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Perform substitutions
    for key, value in substitutions.items():
        placeholder = '$' + key + '$'
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

        # Smart file detection: if value is a path to an existing file, read it
        if os.path.isfile(value):
            try:
                with open(value, 'r', encoding='utf-8') as f:
                    value = f.read()
            except Exception as e:
                print(f"Error reading file '{value}': {e}", file=sys.stderr)
                sys.exit(1)

        substitutions[key] = value

    interpolate_template(template_path, output_path, substitutions)
