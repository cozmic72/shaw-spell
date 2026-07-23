# Supplement generation rules
# Generates supplementary dictionary data from WordNet and Wiktionary

###########################################
# Source data paths
###########################################

WIKTIONARY_JSONL := external/wiktionary/kaikki.org-dictionary-English.jsonl
WORDNET_YAML := external/english-wordnet/src/yaml
READLEX_JSON := external/readlex/readlex.json

###########################################
# Supplement generation (from source data)
###########################################

# The -reliable.json files are COMMITTED artifacts and the anchor identity for
# every editorial patch. Their generators consult the external `shave` tool,
# which is EXPENSIVE (a fixed per-invocation startup cost; re-shaving the whole
# pool is minutes of work). shave is DETERMINISTIC (verified: identical output
# run-to-run, including --confidence 0 pot-luck mode), so a re-shave does NOT
# drift the Shavian or orphan patches — but it's wasteful, so regeneration is a
# DELIBERATE act, not something a stray `git checkout` mtime-shuffle should
# silently trigger. Hence ALL prerequisites are order-only (after `|`): make
# rebuilds -reliable.json only when it is MISSING (e.g. a fresh clone), not when
# a prereq is merely newer. To re-baseline on purpose, use `regenerate-supplements`.
data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json: | $(SRC_TOOLS)/generate_wordnet_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WORDNET_CACHE)
	@echo "Generating WordNet supplement..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wordnet_supplement.py

data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json: | $(SRC_TOOLS)/generate_wiktionary_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WIKTIONARY_JSONL)
	@echo "Generating Wiktionary supplement (this takes a few minutes)..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wiktionary_supplement.py

# Shave-generated slice of the no-IPA WordNet words (net-new + non-zero corpus
# freq) that the reliable/neardot buckets miss. Like the -reliable.json files it
# consults the EXPENSIVE shave tool (fixed per-invocation startup; re-shaving the
# pool is minutes), so its prerequisites are order-only (after `|`): make builds
# it only when MISSING (fresh clone), never on a mere mtime bump — a checkout
# shuffling mtimes must not silently trigger a wasteful re-shave. shave is
# DETERMINISTIC (a re-shave is idempotent, does NOT drift Shaw or orphan patches),
# so this is a deliberateness/cost guard, not an anti-drift one. To re-baseline on
# purpose, delete it and re-make (or use regenerate-supplements below). See
# generate_supplement_speculative.py.
data/supplement-generated.json: | $(SRC_TOOLS)/generate_supplement_speculative.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/apply_frequency_data.py data/supplement-wordnet-speculative.json $(FREQUENCY_CORPUS)
	@echo "Generating shave-spelled supplement from no-IPA WordNet words..."
	$(RUN) python3 $(SRC_TOOLS)/generate_supplement_speculative.py

# Deliberately regenerate the reliable supplements (re-runs the EXPENSIVE shave
# tool — minutes of work; only run when you intend to re-baseline. shave is
# deterministic, so this is idempotent — it won't drift Shaw or orphan patches).
.PHONY: regenerate-supplements
regenerate-supplements:
	rm -f data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json \
	      data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json \
	      data/supplement-generated.json
	@$(MAKE) data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json \
	         data/supplement-generated.json

###########################################
# Confidence re-scoring (fast, uses shave)
###########################################

.PHONY: rescore rescore-full
rescore: data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring supplement confidence..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py

rescore-full: data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring supplement confidence (full shave consultation)..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py --full-shave

###########################################
# Supplement candidate pruning (chained passes)
###########################################

# Pass 0 — untagged-lane fold + proper-noun homograph rescue (wiktionary only).
# Folds the speculative (untagged-accent) records into the chain as RSSB
# unconfirmed-British candidates — the speculative file is an INPUT lane, not a
# reject bin. Then: many kaikki `name` entries have no IPA and were dropped by
# the generator; each is rescued by copying a same-spelling ReadLex homograph's
# IPA and tagged `copied-homograph` for review. Additive: reliable + speculative
# plus the rescued NP0 records. Pass 1 reads this for wiktionary. See
# src/tools/rescue_proper_nouns.py.
data/supplement-wiktionary-rescued.json: $(SRC_TOOLS)/rescue_proper_nouns.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/generate_wiktionary_supplement.py data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json $(WIKTIONARY_JSONL) $(READLEX_JSON)
	@echo "Rescuing IPA-less proper nouns via ReadLex homographs..."
	$(RUN) python3 $(SRC_TOOLS)/rescue_proper_nouns.py

# Pass 0.5 — NEAR syllable-dot correction (wiktionary only). The generator lost
# Wiktionary's syllable dot, so happier /ˈhæp.i.ə/ collapsed to NEAR (𐑣𐑨𐑐𐑽) not
# the two-syllable 𐑣𐑨𐑐𐑦𐑼. Each dot-collapsed NEAR record is re-derived from the
# dotted kaikki sound through the now-fixed converter, capped to needs-review
# confidence and tagged `near-dot-fixed` for the owner to adjudicate (ReadLex is
# editorially inconsistent here). Genuine NEAR (here/weird) and patch-anchored
# records are left untouched. See src/tools/fix_near_syllable_dots.py.
data/supplement-wiktionary-neardot.json: $(SRC_TOOLS)/fix_near_syllable_dots.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/generate_wiktionary_supplement.py data/supplement-wiktionary-rescued.json $(WIKTIONARY_JSONL) data/patches/patches.jsonl
	@echo "Correcting NEAR syllable-dot collapses..."
	$(RUN) python3 $(SRC_TOOLS)/fix_near_syllable_dots.py

# Pass 0.7 — CMUdict IPA fill (names only). The names slice has Shaw but no
# IPA; for names CMUdict knows, ARPABET is mapped to house IPA (real stress)
# and filled ONLY where the derived IPA forward-converts back to the record's
# existing Shaw (independent round-trip confirmation — this is the dictionary,
# unconfirmed IPA is left absent for the owner-gated neural fill). Filled
# records carry ipa_source="cmu". Deterministic (no shave), so ordinary
# mtime-triggered prerequisites are safe. Combine reads this instead of
# supplement-names.json. See src/tools/fill_names_ipa.py.
data/supplement-names-ipa.json: $(SRC_TOOLS)/fill_names_ipa.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/basis.py data/supplement-names.json external/cmudict/cmudict.dict
	@echo "Filling names IPA from CMUdict..."
	$(RUN) python3 $(SRC_TOOLS)/fill_names_ipa.py

# Pass 0.8 — neural G2P IPA fill (generated slice only). The generated slice
# has Shaw but no IPA (shave spelled it Roman->Shavian directly); the frozen
# Latin+Shavian->RP-IPA model (data/g2p-model/, committed artifact) predicts
# house IPA, filled ONLY where BOTH voter gates pass: the prediction
# forward-converts back to the record's exact Shaw (round-trip) AND the model
# likelihood clears the calibrated threshold (see fill_generated_ipa.py).
# Failing records keep no ipa — this is the dictionary, nothing low-confidence
# ships. Filled records carry ipa_source="model-g2p" plus a calibrated numeric
# confidence. Deterministic (greedy CPU decode, no shave), so ordinary
# mtime-triggered prerequisites are safe. Combine reads this instead of
# supplement-generated.json. See src/tools/fill_generated_ipa.py.
data/supplement-generated-ipa.json: $(SRC_TOOLS)/fill_generated_ipa.py $(SRC_TOOLS)/g2p_common.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/basis.py data/supplement-generated.json data/g2p-model/model.pt data/g2p-model/meta.json
	@echo "Filling generated IPA from the frozen neural G2P..."
	$(RUN) python3 $(SRC_TOOLS)/fill_generated_ipa.py

# Supplement preprocessing — ONE in-memory pipeline, ONE recipe, ONE output.
#
# build_supplement.py is the orchestrator: it LOADS the source pools + upstream +
# patches + definition/phrase indexes ONCE, composes every preprocessing transform
# IN MEMORY (combine -> annotate -> dedup -> classify_mergers -> reclassify_rrp ->
# generate_rrp -> collapse -> decontaminate -> phrases), and WRITES
# supplement-combined-filtered.json ONCE. The previous nine per-stage targets
# (combined-raw ... combined-decontaminated) round-tripped JSON through disk and
# encoded the real step ordering in Python hardcoded paths, not these prerequisites
# — so `make -j` could race and corrupt the build. Now the orchestrator OWNS the
# ordering in one process, so the whole chain is a SINGLE recipe and -j-safe by
# construction. Each step module keeps a thin CLI main() for single-stage
# debugging; the orchestrator imports and calls their PURE transform functions.
#
# Prerequisites below are the UNION of everything the composed chain reads: the
# orchestrator + every step module + the shared helpers (basis, dialect_mergers,
# rrp_classifier, rrp_generator, ipa_to_shavian, detect_phrase_divergence, the two
# generator modules whose POS_MAP/synset logic the definition annotator reuses) +
# the data inputs (the three source pools, upstream ReadLex, the WordNet YAML and
# Wiktionary JSONL the definition indexes read, and patches — read-only — for the
# dedup/contamination/phrase anchor-exemption). For debugging, the orchestrator's
# --dump flag re-emits the old per-stage intermediates, but Make never depends on
# them: ordering lives in the orchestrator, not the build graph.
SUPPLEMENT_STEP_MODULES := \
	$(SRC_TOOLS)/build_supplement.py \
	$(SRC_TOOLS)/combine_supplements.py \
	$(SRC_TOOLS)/annotate_definitions.py \
	$(SRC_TOOLS)/filter_supplement_duplicates.py \
	$(SRC_TOOLS)/classify_dialect_mergers.py \
	$(SRC_TOOLS)/reclassify_rrp.py \
	$(SRC_TOOLS)/generate_rrp.py \
	$(SRC_TOOLS)/collapse_identical_dialects.py \
	$(SRC_TOOLS)/filter_supplement_contamination.py \
	$(SRC_TOOLS)/filter_supplement_phrases.py \
	$(SRC_TOOLS)/score_confidence_blend.py \
	$(SRC_TOOLS)/basis.py \
	$(SRC_TOOLS)/dialect_mergers.py \
	$(SRC_TOOLS)/rrp_classifier.py \
	$(SRC_TOOLS)/rrp_generator.py \
	$(SRC_TOOLS)/ipa_to_shavian.py \
	$(SRC_TOOLS)/detect_phrase_divergence.py \
	$(SRC_TOOLS)/generate_wordnet_supplement.py \
	$(SRC_TOOLS)/generate_wiktionary_supplement.py \
	$(SRC_TOOLS)/g2p_common.py

# data/g2p-judge-model (the LATIN-ONLY sibling of data/g2p-model) backs
# reclassify_rrp's feature-flagged MODEL-JUDGE promotion gate. The gate is OFF
# by default (SHAW_SPELL_MODEL_JUDGE=1 enables it) and the model is loaded
# lazily only when it is on, but the artifacts are unconditional prerequisites
# so a flag-on build rebuilds when the frozen model changes.
data/supplement-combined-filtered.json: $(SUPPLEMENT_STEP_MODULES) \
		data/supplement-wordnet-reliable.json \
		data/supplement-wiktionary-neardot.json \
		data/supplement-wiktionary-reliable.json \
		data/supplement-names-ipa.json \
		data/supplement-generated-ipa.json \
		data/g2p-judge-model/model.pt data/g2p-judge-model/meta.json \
		external/readlex/readlex.json \
		$(WORDNET_YAML) $(WIKTIONARY_JSONL) \
		data/patches/patches.jsonl
	@echo "Building supplement pool (in-memory pipeline, one write)..."
	$(RUN) python3 $(SRC_TOOLS)/build_supplement.py

###########################################
# Merged readlex (combines original + supplements)
###########################################

SUPPLEMENT_DEPS := data/supplement-combined-filtered.json

# readlex.json is produced by a two-stage SEQUENTIAL pipeline so the frequency
# enrichment can never be silently reverted by a rebuild:
#   1. apply_patches.py: patch store + supplements -> readlex-merged.json (intermediate)
#   2. apply_frequency_data.py: readlex-merged.json + corpus -> readlex.json (final)
# The final readlex.json — the thing every downstream target consumes — is only
# "done" after frequency runs, so any rebuild reruns both stages in order.
# (legacy generate_merged_readlex.py is retained on disk but off the build path.)
READLEX_MERGED := data/readlex-merged.json
FREQUENCY_CORPUS := external/frequency-words/content/2018/en/en_full.txt

$(READLEX_MERGED): $(SRC_TOOLS)/apply_patches.py $(SRC_TOOLS)/basis.py $(SRC_TOOLS)/dialect_mergers.py external/readlex/readlex.json $(SUPPLEMENT_DEPS) data/patches/patches.jsonl
	@echo "Applying editorial patches to produce merged readlex..."
	$(RUN) python3 $(SRC_TOOLS)/apply_patches.py --out $(READLEX_MERGED)

$(READLEX_PATH): $(READLEX_MERGED) $(SRC_TOOLS)/apply_frequency_data.py $(SRC_TOOLS)/basis.py $(SRC_TOOLS)/dialect_mergers.py $(SRC_TOOLS)/spelling_variants.py $(FREQUENCY_CORPUS)
	@echo "Filling missing frequency data from subtitle corpus..."
	$(RUN) python3 $(SRC_TOOLS)/apply_frequency_data.py --in $(READLEX_MERGED) --out $(READLEX_PATH)

# Convenience alias — the frequency step is now part of the readlex build itself.
.PHONY: frequency
frequency: $(READLEX_PATH)

# frequency-words is a ~1.4 GB all-languages submodule; setup checks it out lean
# (sparse-checkout, only content/2018/en) so a fresh clone stays ~30 MB.
$(FREQUENCY_CORPUS):
	@$(MAKE) setup

# One-time submodule setup for a fresh clone. Re-runnable and safe on an
# already-populated tree.
.PHONY: setup
setup:
	@src/tools/setup-submodules.sh

###########################################
# Editorial review
###########################################

.PHONY: editorial
editorial: $(SUPPLEMENT_DEPS)
	@echo "Updating editorial CSV files..."
	$(RUN) python3 $(SRC_TOOLS)/generate_editorial_csv.py

###########################################
# Phrase divergence detection (flags multi-word phrases whose pronunciation
# genuinely differs from their component words glued together — keepers — vs
# those that are just concatenation noise. See docs/phrase-divergence.md.)
###########################################

data/phrase-divergence.tsv data/phrase-divergence.json: $(SRC_TOOLS)/detect_phrase_divergence.py $(SRC_TOOLS)/ipa_to_shavian.py data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json external/readlex/readlex.json
	@echo "Detecting phrase divergence..."
	$(RUN) python3 $(SRC_TOOLS)/detect_phrase_divergence.py

.PHONY: phrase-divergence
phrase-divergence: data/phrase-divergence.tsv

###########################################
# Wiktionary definitions
###########################################

data/definitions-wiktionary.json: $(SRC_TOOLS)/extract_wiktionary_definitions.py $(READLEX_PATH) $(WIKTIONARY_JSONL)
	@echo "Extracting Wiktionary definitions..."
	$(RUN) python3 $(SRC_TOOLS)/extract_wiktionary_definitions.py

###########################################
# Review files (for human inspection)
###########################################

.PHONY: review-files
review-files: $(SUPPLEMENT_DEPS) $(READLEX_PATH)
	@echo "Generating review TSVs..."
	$(RUN) python3 $(SRC_TOOLS)/generate_review_files.py

###########################################
# Convenience targets
###########################################

.PHONY: supplements supplements-from-source
supplements: $(READLEX_PATH)
	@echo "✓ All supplements and merged readlex up to date"

supplements-from-source: data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring with full shave..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py --full-shave
	@echo "Applying editorial patches into readlex..."
	$(RUN) python3 $(SRC_TOOLS)/apply_patches.py
	@echo "Generating review files..."
	$(RUN) python3 $(SRC_TOOLS)/generate_review_files.py
	@echo "✓ All supplements rebuilt from source"
