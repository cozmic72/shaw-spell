# Shavian Spelling & ReadLex Conventions Digest

This document consolidates the Shavian spelling rules (from shavian.info/spelling/) and ReadLex conventions (from readlex.pythonanywhere.com/spellingprinciples/) for use by automated tools.

## ReadLex-Specific Conventions

### TSV Format
The ReadLex TSV (`kingsleyreadlexicon.tsv`) has columns: `Latn`, `Shaw`, `POS`, `IPA`, `freq`

### ReadLex JSON Format
Keys are `{Latn}_{POS}_{Shaw}`, values are arrays of entry objects:
```json
{
    "Latn": "word",
    "Shaw": "𐑖𐑱𐑝𐑾𐑯",
    "pos": "POS_TAG",
    "ipa": "IPA_string",
    "freq": 1234,
    "var": "RRP"
}
```

### IPA Shorthands in ReadLex
- **Capital R** in IPA (e.g. `twɜːR`) means linking/intrusive (r) — pronounced in rhotic accents (GenAm, Scottish, Irish) but silent in non-rhotic RP. In Shavian it maps to 𐑼 or is part of an r-colored vowel.
- The `var` field indicates dialect: `RRP` = Rhotic RP (the default ReadLex dialect)

### ReadLex Spelling Principles
1. **Base = modern RP** with rhotic R (all Rs pronounced)
2. **GA preference**: when multiple RP pronunciations exist, closest to General American is favoured
3. **TRAP-BATH split**: default includes the split (𐑭 for BATH words in RP)
4. **Schwa inclusion**: to extent possible, avoiding hyper-correctness
5. **Allophonic /i/**: 𐑦 for weak /i/ or /ɪ/; 𐑰 for stressed /iː/
6. **Allophonic /u/**: 𐑫 for ambiguous weak /u/
7. **CURE vowel**: retains conservative RP /ʊə(r)/ → 𐑫𐑼
8. **Yod-coalescence**: only where both RP and GA share it
9. **Affix rule**: compound Shavian letters (𐑼, 𐑾, 𐑽) prohibited at affix boundaries
10. **Word signs**: 𐑞=the, 𐑑=to, 𐑯=and, 𐑝=of, 𐑓=for (standalone/hyphenated only)
11. **Past tense/plural**: 𐑩𐑛 for -ed, 𐑩𐑟 for -es consistently

### POS Tags (ReadLex uses CLAWS C5 tagset)
Common tags: AT0 (article), AV0 (adverb), AJ0 (adjective), CJC (conjunction), CJS (subordinating conj), DPS (possessive det), DT0 (determiner), ITJ (interjection), NN0 (common noun), NN1 (singular noun), NN2 (plural noun), NP0 (proper noun), PNI (indefinite pronoun), PNP (personal pronoun), PRP (preposition), VBB (base form be), VBD (past be), VBZ (3sg be), VDB (base do), VDD (past do), VHB (base have), VM0 (modal), VVB (base verb), VVD (past verb), VVG (-ing verb), VVN (past participle), VVZ (3sg verb), ZZ0 (letter of alphabet)

## IPA-to-Shavian Mapping (Core)

### Vowels
| IPA | Shavian | Keyword | Notes |
|-----|---------|---------|-------|
| ə | 𐑩 | about | Always unstressed |
| ɜːR / ɜː(r) | 𐑻 | bird, err | Always stressed |
| əR / ə(r) | 𐑼 | better | Always unstressed |
| ʌ | 𐑳 | but, cup | Always stressed |
| iː | 𐑰 | be, see | |
| ɪ | 𐑦 | it, bit | Also final unstressed -y |
| eɪ | 𐑱 | say, make | |
| ɛ / e | 𐑧 | pet, bed | |
| æ | 𐑨 | cat, man | |
| ɑː | 𐑭 | father, bath(RP) | |
| ɔː | 𐑷 | caught, all | |
| ɒ | 𐑪 | not, got | |
| uː | 𐑵 | too, blue | |
| ʊ | 𐑫 | good, book | |
| əʊ / oʊ | 𐑴 | go, no | |
| aɪ | 𐑲 | my, time | |
| ɔɪ | 𐑶 | boy, joy | |
| aʊ | 𐑬 | now, out | |
| ɪə | 𐑾 | idea, area | Stressed or unstressed |
| ɪəR / ɪə(r) | 𐑽 | dear, near | R-colored |
| ɛəR / eə(r) | 𐑺 | air, Mary | R-colored |
| ɑːR / ɑː(r) | 𐑸 | far, car | |
| ɔːR / ɔː(r) | 𐑹 | for, more | |
| ʊə | 𐑫𐑼 | poor, sure | Diphthong |
| juː | 𐑿 (single char) or 𐑘𐑵 | you, new | 𐑿 is a ligature letter |

### Consonants
| IPA | Shavian | Example |
|-----|---------|---------|
| p | 𐑐 | pat |
| b | 𐑚 | bat |
| t | 𐑑 | tip |
| d | 𐑛 | dip |
| k | 𐑒 | kit |
| ɡ | 𐑜 | got |
| f | 𐑓 | fit |
| v | 𐑝 | van |
| θ | 𐑔 | think |
| ð | 𐑞 | this |
| s | 𐑕 | sit |
| z | 𐑟 | zoo |
| ʃ | 𐑖 | ship |
| ʒ | 𐑠 | vision |
| tʃ / ʧ | 𐑗 | chop |
| dʒ / ʤ | 𐑡 | jug |
| m | 𐑥 | mat |
| n | 𐑯 | nit |
| ŋ | 𐑙 | ring |
| l | 𐑤 | lit |
| ɹ / r | 𐑮 | rat |
| w | 𐑢 | wit |
| h | 𐑣 | hat |
| j | 𐑘 | yet |

### Special Rules
1. **Naming dot** (·) precedes proper names
2. **No apostrophes** in contractions or possessives
3. **Stress determines vowel choice**: 𐑩 (unstressed) vs 𐑳 (stressed) for schwa/strut
4. **R-coloring**: 𐑼 (unstressed) vs 𐑻 (stressed) for nurse/letter distinction
5. **Final unstressed -y**: always 𐑦 (not 𐑰)
6. **Doubled consonants**: only when sound is actually doubled (e.g. unnamed 𐑳𐑯𐑯𐑱𐑥𐑛)
7. **NG**: always 𐑙 (never 𐑯𐑜); think = 𐑔𐑦𐑙𐑒
8. **Word signs**: the=𐑞, to=𐑑, and=𐑯, of=𐑝, for=𐑓 (standalone only)

### Britfone IPA Differences
Britfone uses strict IPA which differs from ReadLex:
- Britfone /ɐ/ = ReadLex /ʌ/ → 𐑳
- Britfone /ɹ/ = ReadLex /R/ or /r/ → 𐑮
- Britfone /ɛ/ = ReadLex /e/ → 𐑧
- Britfone /ɜː/ = ReadLex /ɜːR/ → 𐑻
- Britfone marks primary stress with ˈ and secondary with ˌ on vowels
- Britfone separates phonemes with spaces
