#!/bin/bash
#
# Shaw-Spell Uninstaller
#
# Removes all Shaw-Spell components from the system.
#

set -e

echo "Shaw-Spell Uninstaller"
echo "====================="
echo ""

# Determine what's installed
USER_DICTS_INSTALLED=false
SYSTEM_DICTS_INSTALLED=false
USER_SPELLING_INSTALLED=false
SYSTEM_SPELLING_INSTALLED=false
USER_SERVICE_INSTALLED=false
SYSTEM_SERVICE_INSTALLED=false
LAUNCH_AGENT_INSTALLED=false

# Check user directories
if ls "$HOME/Library/Dictionaries/"*Shavian* 2>/dev/null | grep -q .; then
    USER_DICTS_INSTALLED=true
fi
if ls "$HOME/Library/Spelling/shaw-"* 2>/dev/null | grep -q .; then
    USER_SPELLING_INSTALLED=true
fi
if [ -d "$HOME/Library/Services/ShavianSpellServer.service" ]; then
    USER_SERVICE_INSTALLED=true
fi
if [ -f "$HOME/Library/LaunchAgents/io.joro.shaw-spell.spellserver.plist" ]; then
    LAUNCH_AGENT_INSTALLED=true
fi

# Check system directories
if ls /Library/Dictionaries/*Shavian* 2>/dev/null | grep -q .; then
    SYSTEM_DICTS_INSTALLED=true
fi
if ls /Library/Spelling/shaw-* 2>/dev/null | grep -q .; then
    SYSTEM_SPELLING_INSTALLED=true
fi
if [ -d /Library/Services/ShavianSpellServer.service ]; then
    SYSTEM_SERVICE_INSTALLED=true
fi

# Show what will be removed
echo "The following components will be removed:"
echo ""

if [ "$USER_DICTS_INSTALLED" = true ]; then
    echo "  User Dictionaries:"
    ls "$HOME/Library/Dictionaries/"*Shavian* 2>/dev/null | sed 's/^/    - /'
fi

if [ "$SYSTEM_DICTS_INSTALLED" = true ]; then
    echo "  System Dictionaries (requires admin):"
    ls /Library/Dictionaries/*Shavian* 2>/dev/null | sed 's/^/    - /'
fi

if [ "$USER_SPELLING_INSTALLED" = true ]; then
    echo "  User Hunspell Dictionaries:"
    ls "$HOME/Library/Spelling/shaw-"* 2>/dev/null | sed 's/^/    - /'
fi

if [ "$SYSTEM_SPELLING_INSTALLED" = true ]; then
    echo "  System Hunspell Dictionaries (requires admin):"
    ls /Library/Spelling/shaw-* 2>/dev/null | sed 's/^/    - /'
fi

if [ "$USER_SERVICE_INSTALLED" = true ]; then
    echo "  User Spell Server:"
    echo "    - $HOME/Library/Services/ShavianSpellServer.service"
fi

if [ "$SYSTEM_SERVICE_INSTALLED" = true ]; then
    echo "  System Spell Server (requires admin):"
    echo "    - /Library/Services/ShavianSpellServer.service"
fi

if [ "$LAUNCH_AGENT_INSTALLED" = true ]; then
    echo "  LaunchAgent:"
    echo "    - $HOME/Library/LaunchAgents/io.joro.shaw-spell.spellserver.plist"
fi

# Check if anything is installed
if [ "$USER_DICTS_INSTALLED" = false ] && \
   [ "$SYSTEM_DICTS_INSTALLED" = false ] && \
   [ "$USER_SPELLING_INSTALLED" = false ] && \
   [ "$SYSTEM_SPELLING_INSTALLED" = false ] && \
   [ "$USER_SERVICE_INSTALLED" = false ] && \
   [ "$SYSTEM_SERVICE_INSTALLED" = false ] && \
   [ "$LAUNCH_AGENT_INSTALLED" = false ]; then
    echo "  Nothing found - Shaw-Spell does not appear to be installed."
    echo ""
    exit 0
fi

echo ""
read -p "Continue with uninstallation? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Uninstallation cancelled."
    exit 0
fi

echo ""
echo "Uninstalling..."
echo ""

# Stop and remove LaunchAgent
if [ "$LAUNCH_AGENT_INSTALLED" = true ]; then
    echo "Stopping spell server..."
    launchctl unload "$HOME/Library/LaunchAgents/io.joro.shaw-spell.spellserver.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/io.joro.shaw-spell.spellserver.plist"
    # Also remove old plist if it exists
    launchctl unload "$HOME/Library/LaunchAgents/org.shavian.spellserver.plist" 2>/dev/null || true
    rm -f "$HOME/Library/LaunchAgents/org.shavian.spellserver.plist"
fi

# Remove user components
if [ "$USER_DICTS_INSTALLED" = true ]; then
    echo "Removing user dictionaries..."
    rm -rf "$HOME/Library/Dictionaries/"*Shavian* 2>/dev/null || true
    rm -rf "$HOME/Library/Dictionaries/"*shavian* 2>/dev/null || true
    touch "$HOME/Library/Dictionaries"
fi

if [ "$USER_SPELLING_INSTALLED" = true ]; then
    echo "Removing user Hunspell dictionaries..."
    rm -f "$HOME/Library/Spelling/shaw-"* 2>/dev/null || true
fi

if [ "$USER_SERVICE_INSTALLED" = true ]; then
    echo "Removing user spell server..."
    rm -rf "$HOME/Library/Services/ShavianSpellServer.service"
fi

# Remove system components (requires sudo)
NEED_SUDO=false
if [ "$SYSTEM_DICTS_INSTALLED" = true ] || \
   [ "$SYSTEM_SPELLING_INSTALLED" = true ] || \
   [ "$SYSTEM_SERVICE_INSTALLED" = true ]; then
    NEED_SUDO=true
fi

if [ "$NEED_SUDO" = true ]; then
    echo ""
    echo "Administrator password required to remove system-wide components..."

    if [ "$SYSTEM_DICTS_INSTALLED" = true ]; then
        echo "Removing system dictionaries..."
        sudo rm -rf /Library/Dictionaries/*Shavian* 2>/dev/null || true
        sudo rm -rf /Library/Dictionaries/*shavian* 2>/dev/null || true
    fi

    if [ "$SYSTEM_SPELLING_INSTALLED" = true ]; then
        echo "Removing system Hunspell dictionaries..."
        sudo rm -f /Library/Spelling/shaw-* 2>/dev/null || true
    fi

    if [ "$SYSTEM_SERVICE_INSTALLED" = true ]; then
        echo "Removing system spell server..."
        sudo rm -rf /Library/Services/ShavianSpellServer.service
    fi
fi

# Update system services
echo "Updating system services..."
/System/Library/CoreServices/pbs -update 2>/dev/null || true

echo ""
echo "Uninstallation complete!"
echo ""
echo "Note: You may want to also remove:"
echo "  - Log file: $HOME/Library/Logs/ShavianSpellServer.log"
echo "  - User preference: defaults delete ShavianDialect"
echo ""
echo "Please restart Dictionary.app if it's running."
