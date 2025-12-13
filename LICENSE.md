# License

Shaw-Spell is a composite project that includes several components under different licenses.

## Shaw-Spell Project Code

The original code for Shaw-Spell (build scripts, installer, spell server, and integration code) is:

**Copyright (c) 2025 joro.io**

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## Third-Party Components

This project bundles and depends on several third-party components, each with their own licenses:

### 1. Readlex

Shavian word data from: https://github.com/Shavian-info/readlex

**License**: MIT License
**Copyright**: (c) 2024 Shavian-info

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

### 2. Open English WordNet

Dictionary definitions from: https://github.com/globalwordnet/english-wordnet

**License**: Creative Commons Attribution 4.0 International (CC BY 4.0)
**Copyright**: Open English WordNet team
**Derived from**: Princeton WordNet 3.0

This resource is derived from Princeton WordNet under the WordNet License
and further developed under the Creative Commons Attribution 4.0 International License.

**Attribution Required**: You must give appropriate credit to both Princeton WordNet
and the Open English WordNet team when distributing this data.

Full CC BY 4.0 License: https://creativecommons.org/licenses/by/4.0/legalcode

**Princeton WordNet 3.0 License**:

Copyright 2006 by Princeton University. All rights reserved.

Permission to use, copy, modify and distribute this software and database
and its documentation for any purpose and without fee or royalty is hereby
granted, provided that you agree to comply with the following copyright
notice and statements, including the disclaimer, and that the same appear
on ALL copies of the software, database and documentation, including
modifications that you make for internal use or for distribution.

WordNet 3.0 Copyright 2006 by Princeton University. All rights reserved.

THIS SOFTWARE AND DATABASE IS PROVIDED "AS IS" AND PRINCETON UNIVERSITY
MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR IMPLIED. BY WAY OF
EXAMPLE, BUT NOT LIMITATION, PRINCETON UNIVERSITY MAKES NO REPRESENTATIONS
OR WARRANTIES OF MERCHANT- ABILITY OR FITNESS FOR ANY PARTICULAR PURPOSE
OR THAT THE USE OF THE LICENSED SOFTWARE, DATABASE OR DOCUMENTATION WILL
NOT INFRINGE ANY THIRD PARTY PATENTS, COPYRIGHTS, TRADEMARKS OR OTHER RIGHTS.

The name of Princeton University or Princeton may not be used in advertising
or publicity pertaining to distribution of the software and/or database.
Title to copyright in this software, database and any associated documentation
shall at all times remain with Princeton University and LICENSEE agrees to
preserve same.

---

### 3. Hunspell

Spell checking library: https://hunspell.github.io/

**License**: Tri-licensed under GPL-2.0 OR LGPL-2.1 OR MPL-1.1
**Copyright**: (C) 2002-2022 Németh László and contributors

Shaw-Spell bundles the Hunspell library. You may choose to use Hunspell under
any one of these licenses:

- **GNU General Public License v2.0** (GPL-2.0)
- **GNU Lesser General Public License v2.1** (LGPL-2.1)
- **Mozilla Public License v1.1** (MPL-1.1)

For the purposes of Shaw-Spell distribution, we utilize Hunspell under the
**LGPL-2.1** license, which permits linking with this software.

**LGPL-2.1 Summary**: The GNU Lesser General Public License allows this
software to be used in conjunction with proprietary software, provided that
the LGPL'd component (Hunspell) remains available under the LGPL terms.

Full license texts:
- GPL-2.0: https://www.gnu.org/licenses/old-licenses/gpl-2.0.html
- LGPL-2.1: https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html
- MPL-1.1: https://www.mozilla.org/en-US/MPL/1.1/

---

## Summary

| Component | License | Usage |
|-----------|---------|-------|
| Shaw-Spell code | MIT | Original code for this project |
| Readlex | MIT | Shavian word mappings |
| Open English WordNet | CC BY 4.0 | Dictionary definitions and spell-checking word lists |
| Princeton WordNet 3.0 | WordNet License | Source for Open English WordNet |
| Hunspell | GPL-2/LGPL-2.1/MPL-1.1 | Spell checking library (used under LGPL-2.1) |

---

## Attribution

When redistributing Shaw-Spell or its derivative works:

1. **Include this LICENSE.md file** or equivalent attribution
2. **Credit Open English WordNet**: "Dictionary definitions from Open English WordNet,
   derived from Princeton WordNet 3.0 (Copyright 2006 Princeton University)"
3. **Credit Readlex**: "Shavian word data from Readlex (Copyright 2024 Shavian-info)"
4. **Credit Hunspell**: "Spell checking powered by Hunspell (Copyright 2002-2022 Németh László)"
5. **Indicate modifications** if you've modified any of the bundled data

---

Last updated: 2025-12-13
