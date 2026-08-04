# Card headline: the two-tier model

Design notes for `src/site/card.cgi`'s headline and sub-lines. Written at the
end of an exploration; the parts marked OPEN were never rendered and are not
decided.

## The shape

    line 1:  {source inflection} [{target inflection} /IPA/]+
    line 2:  {inflection form} of {source lemma} [{target lemma} /IPA/]+
    then:    glosses

The repeat (`+`) is the same at both tiers, so heteronyms — several target
spellings for one source word — need no separate mechanism.

## Why the searched form leads

A reader who looks up `spellings` asked about that form, not the paradigm.
Leading with it and PRUNING the sibling inflections is what frees the space
for glosses; the two changes are one idea, not two.

Naming the relationship in prose (`plural of spelling`) rather than by
position also solves a problem the bare stacked pair had: two lines of
`{latin} {shavian} /ipa/` are hard to tell apart at a glance. No extra visual
cue is needed on top, and `also:` was rejected as a label — it earned nothing.

## What the data says

Measured over `data/site-data/english-shavian-gb-summaries.json` and
`data/readlex.json`. Re-derive before trusting: several numbers in this
project's history were wrong twice before they were right.

| fact | count |
|---|---|
| words with 2 Shavian spellings (namer dot ignored) | 231 |
| words with 3 | 2 (`bode`, `co` — abbreviation/name oddities) |
| forms carrying a variant | 1,016 of 38,666 (2.6%) |
| entries with ≤1 form AND definitions | 33,829 (58%) |
| inflected spellings in >1 POS slot | 8,950 of 41,762 (21.4%) |

⚠ Counting spellings WITHOUT stripping the naming dot inflates the multi-
spelling figure (18 words at 3+): `·𐑜𐑪𐑛` and `𐑜𐑪𐑛` are one word, not two.

The 58% is what makes glosses-in-spare-space worth building: on well over half
of all cards there is room going spare, currently spent on a bare count.

## Multi-POS splits three ways

An inflected spelling often belongs to more than one slot. The cases want
different treatment and must not be conflated:

1. **Syncretism — 5,604 spellings, 98% VVD+VVN.** `abased` is past tense AND
   past participle of one lemma. One line, merged label. The common case.
2. **Cross-lemma spelling variants** — `abridgement`/`abridgment`,
   `acclimatise`/`acclimatize`. Same word, two lemma spellings; showing both
   is noise.
3. **Genuine ambiguity** — `𐑨𐑒𐑕𐑧𐑕𐑩𐑟` is NN2 and VVZ of `access`. Two real
   answers to "a form of what".

## OPEN — not decided, never rendered

- **`rows` is the worst case and the model strains on it.** A search returns
  TWO entries (`latn_row_0` noun-plural 𐑮𐑴𐑟, `latn_row_2` verb-3sg 𐑮𐑬𐑟), so
  line 2 has two relationships to name, both pointing at the Latin lemma
  `row`. Line 1's repeat copes; line 2 does not obviously.
- **What line 2 holds when the search IS the lemma.** There is no "X of Y"
  relationship then — does the tier vanish?
- **Whether pruned inflections deserve any trace** (a count? nothing?).
- **How many glosses to show**, and by what rule — remaining room, gloss
  length, or a fixed cap.
- **Variants**: the working idea is to keep them out of the headline and
  carry them on the lemma line. ⚠ But on heteronyms the `variant` field holds
  the OTHER heteronym's form, not an accent variant — `latn_row_0`'s plural
  carries `variant='𐑮𐑬𐑟 /raʊz/'`. There the repeat and the variant slot
  would state the same fact twice; the repeat should own it.

## Constraints any implementation must keep

- Degrade to today's rendering for a single-spelling, single-form entry.
  231 of ~50,000 words are affected; ordinary cards must cost nothing.
- 1200×630, opaque, under 600 KB; the wrap-before-illegible ladder; the
  `·𐑖𐑷-𐑕𐑐𐑧𐑤 ©joro.io` signature with its hyphen and naming dot exact.
- IPA renders in InterAlia. Bernie Sans has no IPA glyphs at all, so IPA
  inside a parenthesised group needs the IPA font too, or it draws tofu.
