# DMG Layout Template

This directory contains the template for customizing the DMG window layout. The `DS_Store_template` file is a non-hidden copy of `.DS_Store` that won't be modified by the OS when viewing this directory.

## How to Customize the DMG Layout

**Important:** The .DS_Store must be created from a mounted DMG volume, not a regular folder, for all settings (window size, icon size, positions) to work correctly.

1. **Build the DMG first**:
   ```bash
   make dmg
   ```

2. **Create a writable copy for customization**:
   ```bash
   hdiutil convert build/ShawSpellInstaller.dmg -format UDRW -o build/dmg-customize.dmg
   ```

3. **Mount it and open in Finder**:
   ```bash
   open build/dmg-customize.dmg
   # Wait for it to mount, then customize in Finder
   ```

4. **Customize the Finder window** of the mounted DMG:
   - Resize the window to your preferred size
   - Switch to Icon View (View → as Icons)
   - Arrange the two app icons where you want them
   - Adjust icon size (View → Show View Options)
   - Set any other view preferences

5. **Copy the .DS_Store file to the template**:
   ```bash
   cp /Volumes/Shaw\ Spell\ Installer/.DS_Store src/installer/dmg-template/DS_Store_template
   ```

6. **Eject and clean up**:
   ```bash
   hdiutil detach /Volumes/Shaw\ Spell\ Installer
   rm build/dmg-customize.dmg
   ```

7. **Rebuild the DMG** - it will now use your custom layout:
   ```bash
   make dmg
   ```

## Notes

- The `DS_Store_template` file is a binary file that stores Finder view settings
- Stored as a non-hidden file so the OS won't modify it when viewing this directory
- It's specific to the "Shaw-Spell Installer" volume name
- If you change the volume name in the Makefile, you'll need to recreate the template
- The build will work fine without a template - it just uses default layout
