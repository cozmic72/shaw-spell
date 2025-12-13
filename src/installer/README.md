# Shaw-Spell Installer

Native macOS installer application for Shaw-Spell - Shavian Dictionaries & Spell Checker.

## Overview

This is a graphical installer app that provides a user-friendly way to install Shaw-Spell on macOS. It offers options for:

- **Dialect selection**: British English (GB), American English (US), or both
- **Installation scope**: User-only or system-wide (requires admin password)
- **Automatic setup**: Installs dictionaries, Hunspell files, and spell server service

## Building

From the project root:

```bash
make installer    # Build the installer app
make dmg          # Build the installer app and create DMG
```

This will:
1. Create the app icon from the project SVG icon
2. Compile the Objective-C source files
3. Build the application bundle at `build/Install Shaw-Spell.app`
4. Code sign the app (if signing identity is available)
5. (For `make dmg`) Package into a DMG at `build/ShawSpellInstaller.dmg`

## Running

From the project root:

```bash
open "build/Install Shaw-Spell.app"
```

## Requirements

- macOS 10.13 or later
- Xcode Command Line Tools (for building)
- librsvg (for icon generation): `brew install librsvg`
- Code signing identity (optional, for distribution)

## Structure

- `src/main.m` - Application entry point
- `src/InstallerAppDelegate.h/m` - Main application logic and UI
- `src/Info.plist` - Bundle configuration
- `assets/AppIcon.icns` - Application icon (generated from project icon)
- `create-icon.sh` - Script to generate app icon from source PNG

## What It Installs

The installer will install the selected components to:

### User Installation (default)
- Dictionaries → `~/Library/Dictionaries/`
- Hunspell files → `~/Library/Spelling/`
- Spell server → `~/Library/Services/`
- LaunchAgent → `~/Library/LaunchAgents/`

### System-Wide Installation (requires admin)
- Dictionaries → `/Library/Dictionaries/`
- Hunspell files → `/Library/Spelling/`
- Spell server → `/Library/Services/`
- LaunchAgent → `~/Library/LaunchAgents/` (always user-specific)

## Features

- **Clean UI**: Native macOS interface with Cocoa
- **Dialect options**: Install British, American, or both variants
- **Scope selection**: User or system-wide installation
- **Progress feedback**: Progress indicator and status messages
- **Installation verification**: Error handling and success confirmation
- **Post-install instructions**: Guides user on next steps

## Development

The installer is written in Objective-C using the Cocoa framework. It:

1. Builds a bash script based on user selections
2. Executes the script (with sudo if system-wide)
3. Copies dictionary bundles, Hunspell files, and spell server
4. Configures LaunchAgent for automatic spell server startup
5. Updates system services

## Code Signing

The Makefile attempts to code sign with the identity "Jonathan Ross". To change this:

```bash
make CODESIGN_IDENTITY="Your Name"
```

Code signing is optional for local testing but required for distribution.

## Clean

```bash
make clean
```

This removes:
- Build artifacts in `build/`
- Compiled object files in `src/`
- Generated icon file `assets/AppIcon.icns`
