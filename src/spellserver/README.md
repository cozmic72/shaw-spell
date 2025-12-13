# Shavian Spell Server

NSSpellServer service providing native macOS spell-checking for English with Shavian script support.

## Overview

This service registers as an English spell checker that handles **both Latin and Shavian orthography**:

- **Shavian text** (𐑐-𐑿): Checked against Shavian Hunspell dictionary (75K+ words)
- **Latin text** (a-z): Checked against English Hunspell dictionary (en_GB)

Users don't need to switch languages—the service automatically detects the script and routes to the appropriate dictionary.

## Regional Variants

The spell server registers for multiple English variants:
- `English` (generic)
- `en_US` (US English - Gen-Am)
- `en_GB` (UK English - RP)
- `en_AU` (Australian English)
- `en_CA` (Canadian English)
- `en_NZ` (New Zealand English)

Currently, all variants use the same Shavian dictionary which contains words from multiple regional variants (RRP, GA, AU). Future enhancement: filter suggestions based on the selected variant.

## Requirements

- macOS 10.10+
- Hunspell library (`brew install hunspell`)
- Shavian Hunspell dictionary installed at `~/Library/Spelling/shaw.{dic,aff}`
- English Hunspell dictionary installed at `~/Library/Spelling/en_GB.{dic,aff}`

## Building

```bash
make
```

This compiles the service and creates `build/ShavianSpellServer.service`.

## Installing

```bash
make install
```

This:
1. Copies the service bundle to `~/Library/Services/`
2. Updates the system services database

**Important**: You may need to **log out and log back in** for the service to appear in System Settings.

## Testing

After installation:

1. Open **System Settings** > **Keyboard** > **Text Input**
2. Click **Edit...** next to "Spelling"
3. Look for **ShawDict** spell checkers in the list
4. Enable the variant you want (e.g., "ShawDict - English (US)")

Test in any native app (TextEdit, Pages, Mail):
- Type some Shavian text: 𐑖𐑱𐑝𐑾𐑯
- Type a misspelled Shavian word: 𐑖𐑱𐑝𐑾𐑯𐑟𐑟𐑟
- Latin text should still use system spell-checking

## Uninstalling

```bash
make uninstall
```

## How It Works

### Architecture

1. **main.m**: Creates NSSpellServer and registers for all English variants
2. **ShavianSpellChecker**: Implements NSSpellServerDelegate
   - Loads two Hunspell dictionaries: Shavian and English
   - Detects script (Shavian vs Latin) using Unicode ranges
   - Routes Shavian text to Hunspell (`shaw.dic`)
   - Routes Latin text to Hunspell (`en_GB.dic`)
3. **Custom word boundary detection**: Manual implementation since NSLinguisticTagger doesn't recognize Shavian as letters

### Script Detection

Shavian Unicode range: `U+10450` to `U+1047F`

The service scans each word and:
- If it contains any Shavian characters → use Hunspell
- Otherwise → delegate to system checker

This allows mixed-script documents to work seamlessly.

### Suggestions

When providing spelling suggestions:
- **Shavian words**: Hunspell provides up to 10 suggestions from Shavian dictionary
- **Latin words**: Hunspell provides up to 10 suggestions from English dictionary

Both use the same Hunspell suggestion algorithm for consistency.

## Future Enhancements

- [ ] Variant-aware suggestions (prefer RRP for en_GB, GA for en_US, etc.)
- [ ] Separate Hunspell dictionaries per variant
- [ ] Learning capability (remember user-added words)
- [ ] Grammar checking for Shavian

## Troubleshooting

### Service doesn't appear in System Settings

Try:
```bash
/System/Library/CoreServices/pbs -flush
/System/Library/CoreServices/pbs -update
```

Then log out and log back in.

### Hunspell not found during build

Install Hunspell:
```bash
brew install hunspell
```

### Dictionary not found at runtime

Ensure the Shavian dictionary is installed:
```bash
./build.sh spellcheck install
ls ~/Library/Spelling/shaw.dic
```

## Development

To rebuild after changes:
```bash
make clean
make install
```

Check Console.app for NSSpellServer logs:
```
ShavianSpellServer: Registered en_US spell checker
ShavianSpellServer: Loaded Hunspell dictionary from ...
```

## License

Part of the shaw-dict project. See main project LICENSE for details.
