#!/usr/bin/env python3
"""
Generate all icons for Shaw-Spell:
- Website favicons (multiple sizes)
- Apple touch icons for mobile
- macOS app icon (.icns)
- Uninstaller app icon (.icns)
- DMG volume icon (.icns)

All icons use the Ormin font with red color scheme (#E74C3C).
"""

from PIL import Image, ImageDraw, ImageFont
import subprocess
import shutil
from pathlib import Path


def create_base_icon(size, font_path, bg_color='white', text_color=(231, 76, 60),
                     text='𐑖𐑕', corner_radius_ratio=0.25, font_size_ratio=0.88, y_position_ratio=0.81):
    """
    Create a base icon with customizable parameters.

    Args:
        size: Icon size in pixels (square)
        font_path: Path to Ormin font file
        bg_color: Background color (white, transparent, or RGB tuple)
        text_color: Text color as RGB tuple
        text: Shavian text to display
        corner_radius_ratio: Corner radius as ratio of size (0 = sharp corners)
        font_size_ratio: Font size as ratio of icon size
        y_position_ratio: Y position as ratio (baseline position, like SVG)
    """
    # Create image
    if bg_color == 'transparent':
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    elif bg_color == 'white':
        img = Image.new('RGBA', (size, size), (255, 255, 255, 255))
    else:
        img = Image.new('RGBA', (size, size), bg_color)

    draw = ImageDraw.Draw(img)

    # Draw text
    font_size = int(size * font_size_ratio)
    font = ImageFont.truetype(str(font_path), font_size)

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center horizontally, position at specified y ratio
    x = (size - text_width) // 2 - bbox[0]
    # y_position_ratio is baseline position (like SVG), so subtract bbox[3] (baseline offset)
    y = int(size * y_position_ratio) - bbox[3]

    # Draw text with slight stroke for boldness
    stroke_width = max(1, size // 32)
    draw.text((x, y), text, font=font, fill=text_color,
              stroke_width=stroke_width, stroke_fill=text_color)

    return img


def create_app_icon(size, font_path, text='𐑖𐑕', padding_ratio=0.0625,
                    corner_radius_ratio=0.178, font_size_ratio=0.82, y_position_ratio=0.796):
    """
    Create macOS app icon with red gradient background and white text.
    Matches the design from src/installer/src/resources/icon.svg.
    """
    # Create image with alpha channel
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Calculate proportions
    padding = int(size * padding_ratio)
    inner_size = size - (2 * padding)
    corner_radius = int(inner_size * corner_radius_ratio)

    # Draw red background (using lighter red from gradient)
    red_color = (231, 76, 60)  # #E74C3C
    draw.rounded_rectangle(
        [(padding, padding), (size - padding - 1, size - padding - 1)],
        radius=corner_radius,
        fill=red_color
    )

    # Draw Shavian text
    font_size = int(size * font_size_ratio)
    font = ImageFont.truetype(str(font_path), font_size)

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center horizontally, position at specified y ratio
    x = (size - text_width) // 2 - bbox[0]
    # y_position_ratio is baseline position (like SVG), so subtract bbox[3] (baseline offset)
    y = int(size * y_position_ratio) - bbox[3]

    # Draw white text with stroke for boldness
    stroke_width = max(1, size // 80)
    draw.text((x, y), text, font=font, fill='white',
              stroke_width=stroke_width, stroke_fill='white')

    return img


def create_uninstaller_icon(size, font_path, text='𐑖𐑕', padding_ratio=0.0625,
                            corner_radius_ratio=0.178, font_size_ratio=0.82, y_position_ratio=0.796):
    """
    Create uninstaller icon with grey gradient background, dimmed text, and prohibition symbol.
    Similar to app icon but with grey theme and prohibition overlay.
    """
    # Create image with alpha channel
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Calculate proportions
    padding = int(size * padding_ratio)
    inner_size = size - (2 * padding)
    corner_radius = int(inner_size * corner_radius_ratio)

    # Draw grey background (darker grey gradient)
    grey_color = (153, 153, 153)  # #999999
    draw.rounded_rectangle(
        [(padding, padding), (size - padding - 1, size - padding - 1)],
        radius=corner_radius,
        fill=grey_color
    )

    # Draw Shavian text (dimmed)
    font_size = int(size * font_size_ratio)
    font = ImageFont.truetype(str(font_path), font_size)

    # Get text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    # Center horizontally, position at specified y ratio
    x = (size - text_width) // 2 - bbox[0]
    # y_position_ratio is baseline position (like SVG), so subtract bbox[3] (baseline offset)
    y = int(size * y_position_ratio) - bbox[3]

    # Draw white text with 50% opacity (dimmed)
    # Create a temporary image for the text with transparency
    text_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_img)
    stroke_width = max(1, size // 80)
    text_draw.text((x, y), text, font=font, fill=(255, 255, 255, 128),
                   stroke_width=stroke_width, stroke_fill=(255, 255, 255, 128))
    img = Image.alpha_composite(img, text_img)

    # Draw prohibition symbol (circle with diagonal line)
    draw = ImageDraw.Draw(img)
    symbol_center_x = int(size * 0.75)  # 384 on 512px
    symbol_center_y = int(size * 0.25)  # 128 on 512px
    symbol_radius = int(size * 0.156)   # 80 on 512px

    # Red circle with white stroke
    red_color = (232, 93, 74)  # #E85D4A
    draw.ellipse(
        [(symbol_center_x - symbol_radius, symbol_center_y - symbol_radius),
         (symbol_center_x + symbol_radius, symbol_center_y + symbol_radius)],
        fill=red_color,
        outline='white',
        width=max(2, size // 64)
    )

    # Diagonal line (top-right to bottom-left)
    line_width = max(4, size // 32)
    offset = int(symbol_radius * 0.7)  # Diagonal offset
    draw.line(
        [(symbol_center_x - offset, symbol_center_y + offset),
         (symbol_center_x + offset, symbol_center_y - offset)],
        fill='white',
        width=line_width
    )

    return img


def create_icns(iconset_dir, output_file):
    """Convert iconset directory to .icns file using iconutil."""
    try:
        subprocess.run(
            ['iconutil', '-c', 'icns', str(iconset_dir), '-o', str(output_file)],
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error running iconutil: {e.stderr.decode()}")
        return False


def generate_favicons(font_path, output_dir):
    """Generate website favicons."""
    print("\n=== Generating Favicons ===")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Standard favicon sizes
    sizes = [32, 64, 128, 192, 512]

    for size in sizes:
        img = create_base_icon(size, font_path, bg_color='white')
        output_path = output_dir / f'favicon-{size}x{size}.png'
        img.save(output_path, 'PNG')
        print(f"  ✓ {output_path.relative_to(output_dir.parent)}")

    # Generate default favicon.ico (32x32)
    img_32 = create_base_icon(32, font_path, bg_color='white')
    favicon_ico = output_dir / 'favicon.ico'
    img_32.save(favicon_ico, 'ICO')
    print(f"  ✓ {favicon_ico.relative_to(output_dir.parent)}")

    # Generate default favicon.png (64x64)
    img_64 = create_base_icon(64, font_path, bg_color='white')
    favicon_png = output_dir / 'favicon.png'
    img_64.save(favicon_png, 'PNG')
    print(f"  ✓ {favicon_png.relative_to(output_dir.parent)}")


def generate_apple_touch_icons(font_path, output_dir):
    """Generate Apple touch icons for mobile."""
    print("\n=== Generating Apple Touch Icons ===")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Apple touch icon sizes (180x180 for iPhone, 192x192 for Android)
    sizes = [
        (180, 'apple-touch-icon-180x180.png'),
        (192, 'apple-touch-icon-192x192.png'),
    ]

    for size, filename in sizes:
        img = create_base_icon(size, font_path, bg_color='white')
        output_path = output_dir / filename
        img.save(output_path, 'PNG')
        print(f"  ✓ {output_path.relative_to(output_dir.parent)}")


def generate_icns_from_function(font_path, output_dir, icon_function, icon_name, output_filename='AppIcon.icns'):
    """
    Generic function to generate .icns file from an icon creation function.

    Args:
        font_path: Path to font file
        output_dir: Directory to output the .icns file
        icon_function: Function to call to create each icon size (e.g., create_app_icon)
        icon_name: Display name for progress messages
        output_filename: Name of the .icns file to create (default: AppIcon.icns)
    """
    print(f"\n=== Generating {icon_name} ===")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use output filename base for iconset directory
    iconset_name = output_filename.replace('.icns', '.iconset')
    iconset_dir = output_dir / iconset_name
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir()

    # Icon sizes required for macOS
    sizes = [
        (16, 'icon_16x16.png'),
        (32, 'icon_16x16@2x.png'),
        (32, 'icon_32x32.png'),
        (64, 'icon_32x32@2x.png'),
        (128, 'icon_128x128.png'),
        (256, 'icon_128x128@2x.png'),
        (256, 'icon_256x256.png'),
        (512, 'icon_256x256@2x.png'),
        (512, 'icon_512x512.png'),
        (1024, 'icon_512x512@2x.png'),
    ]

    print("  Generating PNG files...")
    for size, filename in sizes:
        img = icon_function(size, font_path)
        output_path = iconset_dir / filename
        img.save(output_path, 'PNG')
        print(f"    ✓ {filename}")

    print("  Converting iconset to icns...")
    output_file = output_dir / output_filename
    if not create_icns(iconset_dir, output_file):
        return False

    print("  Cleaning up iconset directory...")
    shutil.rmtree(iconset_dir)

    print(f"  ✓ {output_file.relative_to(output_dir.parent)}")
    return True


def generate_macos_app_icon(font_path, output_dir):
    """Generate macOS app icon (.icns)."""
    return generate_icns_from_function(
        font_path, output_dir, create_app_icon, "macOS App Icon", "installer-AppIcon.icns"
    )


def generate_uninstaller_icon(font_path, output_dir):
    """Generate uninstaller icon (.icns) with grey theme and prohibition symbol."""
    return generate_icns_from_function(
        font_path, output_dir, create_uninstaller_icon, "Uninstaller Icon", "uninstaller-AppIcon.icns"
    )


def generate_dmg_icon(font_path, output_dir):
    """Generate DMG volume icon (.icns) - same as main app icon."""
    return generate_icns_from_function(
        font_path, output_dir, create_app_icon, "DMG Volume Icon", "VolumeIcon.icns"
    )


def main():
    """Generate all icons."""
    # Paths
    script_dir = Path(__file__).parent
    font_path = script_dir.parent / 'fonts' / 'Ormin-Regular.otf'
    build_dir = script_dir.parent.parent / 'build'
    icons_dir = build_dir / 'icons'

    if not font_path.exists():
        print(f"Error: Font not found at {font_path}")
        return 1

    print(f"Generating all icons with Ormin font from {font_path.relative_to(script_dir.parent.parent)}")
    print(f"Output directory: {icons_dir.relative_to(script_dir.parent.parent)}")

    # Generate all icon types to centralized icons directory
    generate_favicons(font_path, icons_dir)
    generate_apple_touch_icons(font_path, icons_dir)
    generate_macos_app_icon(font_path, icons_dir)
    generate_uninstaller_icon(font_path, icons_dir)
    generate_dmg_icon(font_path, icons_dir)

    print("\n✓ All icons generated successfully!")
    print(f"   Location: {icons_dir.relative_to(script_dir.parent.parent)}")
    return 0


if __name__ == '__main__':
    exit(main())
