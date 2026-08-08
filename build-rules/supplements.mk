# Supplement generation rules
# Generates supplementary dictionary data from WordNet and Wiktionary
#
# =========================================================================
# THE COMMITTED-CHECKPOINT MODEL (read this before touching prerequisites)
# =========================================================================
# The expensive pipeline output — the combine→classify→prune supplement pool
# (data/supplement-combined-filtered.json) and its downstream derivations
# (readlex.json, the definition caches) — is COMMITTED to git and IS the build's
# starting point. Downstream targets (dictionaries, editor, macOS dict, spell-
# checker) CONSUME these checkpoints; they do NOT rebuild them. So a normal
# `make dictionaries` on a clean tree runs ZERO slow generators — it just reads
# the checked-in data. This is the whole point: fast builds, no re-running shave
# or the neural fills on every build.
#
# HOW: every committed-checkpoint target uses ORDER-ONLY prerequisites (after
# `|`). Order-only means make rebuilds the target only when it is MISSING (a
# fresh clone with the file absent), NOT when a prerequisite is merely newer.
# This is REQUIRED, not cosmetic: even a pristine `git clone` writes the source
# .py files with newer mtimes than the data/, so with normal prereqs a clean
# checkout would re-fire the entire slow chain. Order-only prevents that.
#
# THE TRADEOFF (important — don't get caught): because the edges are order-only,
# editing a generator .py does NOT auto-rebuild its checkpoint. `make` will
# happily ship the OLD committed data after you edit a generator. To refresh a
# checkpoint on purpose, use the deliberate regenerate-* targets (regenerate-
# supplements / regenerate-supplement-pool) or rm the file
# and re-make. Regeneration is a CONSCIOUS act — the committed data is the source
# of truth, not the generators. (shave is EXPENSIVE but DETERMINISTIC, so a
# re-shave is idempotent and safe — see the per-target notes below.)
# =========================================================================

###########################################
# Source data paths
###########################################

WIKTIONARY_JSONL := external/wiktionary/kaikki.org-dictionary-English.jsonl
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
data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json: | require-shave $(SRC_TOOLS)/generate_wordnet_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WORDNET_CACHE)
	@echo "Generating WordNet supplement..."
	$(RUN) python3 $(SRC_TOOLS)/generate_wordnet_supplement.py

data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json: | require-shave $(SRC_TOOLS)/generate_wiktionary_supplement.py $(SRC_TOOLS)/ipa_to_shavian.py $(WIKTIONARY_JSONL)
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
data/supplement-generated.json: | require-shave $(SRC_TOOLS)/generate_supplement_speculative.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/apply_frequency_data.py data/supplement-wordnet-speculative.json $(FREQUENCY_CORPUS)
	@echo "Generating shave-spelled supplement from no-IPA WordNet words..."
	$(RUN) python3 $(SRC_TOOLS)/generate_supplement_speculative.py

# Deliberately regenerate the reliable supplements (re-runs the EXPENSIVE shave
# tool — minutes of work; only run when you intend to re-baseline. shave is
# deterministic, so this is idempotent — it won't drift Shaw or orphan patches).
.PHONY: regenerate-supplements
regenerate-supplements: require-shave
	rm -f data/supplement-wordnet-reliable.json data/supplement-wordnet-speculative.json \
	      data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json \
	      data/supplement-generated.json
	@$(MAKE) data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json \
	         data/supplement-generated.json

###########################################
# Confidence re-scoring (fast, uses shave)
###########################################

.PHONY: rescore rescore-full
rescore: require-shave data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring supplement confidence..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py

rescore-full: require-shave data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
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
#
# COMMITTED checkpoint: prerequisites are ORDER-ONLY (after `|`) so a fresh
# checkout with the file present is up-to-date and make skips this pass — it
# rebuilds only when the file is MISSING. (Deterministic, so this is a cost/
# deliberateness guard, not anti-drift.) To re-baseline: rm the file and re-make.
data/supplement-wiktionary-rescued.json: | $(SRC_TOOLS)/rescue_proper_nouns.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/generate_wiktionary_supplement.py data/supplement-wiktionary-reliable.json data/supplement-wiktionary-speculative.json $(WIKTIONARY_JSONL) $(READLEX_JSON)
	@echo "Rescuing IPA-less proper nouns via ReadLex homographs..."
	$(RUN) python3 $(SRC_TOOLS)/rescue_proper_nouns.py

# Pass 0.5 — NEAR syllable-dot correction (wiktionary only). The generator lost
# Wiktionary's syllable dot, so happier /ˈhæp.i.ə/ collapsed to NEAR (𐑣𐑨𐑐𐑽) not
# the two-syllable 𐑣𐑨𐑐𐑦𐑼. Each dot-collapsed NEAR record is re-derived from the
# dotted kaikki sound through the now-fixed converter, capped to needs-review
# confidence and tagged `near-dot-fixed` for the owner to adjudicate (ReadLex is
# editorially inconsistent here). Genuine NEAR (here/weird) and patch-anchored
# records are left untouched. See src/tools/fix_near_syllable_dots.py.
#
# COMMITTED checkpoint: ORDER-ONLY prerequisites (see rescued above) — rebuilt
# only when MISSING, not on incidental mtime churn. rm to re-baseline.
data/supplement-wiktionary-neardot.json: | $(SRC_TOOLS)/fix_near_syllable_dots.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/generate_wiktionary_supplement.py data/supplement-wiktionary-rescued.json $(WIKTIONARY_JSONL)
	@echo "Correcting NEAR syllable-dot collapses..."
	$(RUN) python3 $(SRC_TOOLS)/fix_near_syllable_dots.py

# Pass 0.7 — CMUdict IPA fill (names only). The names slice has Shaw but no
# IPA; for names CMUdict knows, ARPABET is mapped to house IPA (real stress)
# and filled ONLY where the derived IPA forward-converts back to the record's
# existing Shaw (independent round-trip confirmation — this is the dictionary,
# unconfirmed IPA is left absent for the owner-gated neural fill). Filled
# records carry ipa_source="cmu". COMMITTED checkpoint with ORDER-ONLY
# prerequisites (see rescued above): rebuilt only when MISSING, not on incidental
# mtime churn — a fresh checkout is up-to-date. rm to re-baseline. Combine reads
# this instead of supplement-names.json. See src/tools/fill_names_ipa.py.
data/supplement-names-ipa.json: | $(SRC_TOOLS)/fill_names_ipa.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/basis.py data/supplement-names.json external/cmudict/cmudict.dict
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
# confidence. COMMITTED checkpoint with ORDER-ONLY prerequisites (see rescued
# above): rebuilt only when MISSING, not on incidental mtime churn — a fresh
# checkout is up-to-date. rm to re-baseline. Combine reads this instead of
# supplement-generated.json. See src/tools/fill_generated_ipa.py.
data/supplement-generated-ipa.json: | $(SRC_TOOLS)/fill_generated_ipa.py $(SRC_TOOLS)/g2p_common.py $(SRC_TOOLS)/ipa_to_shavian.py $(SRC_TOOLS)/basis.py data/supplement-generated.json data/g2p-model/model.pt data/g2p-model/meta.json
	@echo "Filling generated IPA from the frozen neural G2P..."
	$(RUN) python3 $(SRC_TOOLS)/fill_generated_ipa.py

# Supplement preprocessing — ONE in-memory pipeline, ONE recipe, ONE output.
#
# build_supplement.py is the orchestrator: it LOADS the source pools + upstream +
# patches + definition/phrase indexes ONCE, composes every preprocessing transform
# IN MEMORY (combine -> annotate -> dedup -> classify_mergers -> reclassify_rrp ->
# generate_rrp -> collapse -> flag_variants -> decontaminate -> phrases ->
# score -> restore_spelling_marks), and WRITES
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
# rrp_classifier, rrp_generator, ipa_to_shavian, detect_phrase_divergence, the
# wiktionary generator module whose constants the dialect collapse reuses) +
# the data inputs (the three source pools, upstream ReadLex, the definition
# artifact the has_definition annotator indexes, and patches — read-only — for
# the dedup/contamination/phrase anchor-exemption). For debugging, the orchestrator's
# --dump flag re-emits the old per-stage intermediates, but Make never depends on
# them: ordering lives in the orchestrator, not the build graph.
#
# supplement-combined-filtered.json is a COMMITTED checkpoint (see .gitignore),
# and rebuilding it is EXPENSIVE — the orchestrator processes the full ~200 MB
# pool through the whole combine->classify->prune chain (minutes), consuming the
# shave-generated -reliable/neardot/names-ipa/generated-ipa inputs. So, exactly
# like those upstream shave generators, ALL prerequisites are ORDER-ONLY (after
# `|`): make rebuilds the checkpoint only when it is MISSING (e.g. a fresh clone),
# never because a source pool or generator .py merely has a newer mtime (a stray
# `git checkout` mtime-shuffle must not silently trigger the slow chain). The
# transforms are deterministic, so this is a deliberateness/cost guard, not an
# anti-drift one. To re-baseline on purpose: rm the file and re-make, or use the
# regenerate-supplement-pool target below.
SUPPLEMENT_STEP_MODULES := \
	$(SRC_TOOLS)/build_supplement.py \
	$(SRC_TOOLS)/combine_supplements.py \
	$(SRC_TOOLS)/annotate_definitions.py \
	$(SRC_TOOLS)/filter_supplement_duplicates.py \
	$(SRC_TOOLS)/classify_dialect_mergers.py \
	$(SRC_TOOLS)/reclassify_rrp.py \
	$(SRC_TOOLS)/generate_rrp.py \
	$(SRC_TOOLS)/collapse_identical_dialects.py \
	$(SRC_TOOLS)/flag_variants.py \
	$(SRC_TOOLS)/filter_supplement_contamination.py \
	$(SRC_TOOLS)/filter_supplement_phrases.py \
	$(SRC_TOOLS)/score_confidence_blend.py \
	$(SRC_TOOLS)/restore_spelling_marks.py \
	$(SRC_TOOLS)/basis.py \
	$(SRC_TOOLS)/dialect_mergers.py \
	$(SRC_TOOLS)/rrp_classifier.py \
	$(SRC_TOOLS)/rrp_generator.py \
	$(SRC_TOOLS)/ipa_to_shavian.py \
	$(SRC_TOOLS)/detect_phrase_divergence.py \
	$(SRC_TOOLS)/generate_wiktionary_supplement.py \
	$(SRC_TOOLS)/g2p_common.py

# data/g2p-judge-model (the LATIN-ONLY sibling of data/g2p-model) backs
# reclassify_rrp's MODEL-JUDGE promotion gate. The gate is ON by default
# (reclassify_rrp.ENABLE_MODEL_JUDGE): every candidate the classifier would
# promote to RRP must pass the Latin-only RP-IPA judge or it stays in its
# source var as a review candidate. SHAW_SPELL_MODEL_JUDGE=0 turns it OFF,
# restoring the pure source-var rule; =1 is redundant. The artifacts are
# unconditional prerequisites so the build rebuilds when the frozen model
# changes.
data/supplement-combined-filtered.json: | $(SUPPLEMENT_STEP_MODULES) \
		data/supplement-wordnet-reliable.json \
		data/supplement-wiktionary-neardot.json \
		data/supplement-wiktionary-reliable.json \
		data/supplement-names-ipa.json \
		data/supplement-generated-ipa.json \
		data/g2p-judge-model/model.pt data/g2p-judge-model/meta.json \
		external/readlex/readlex.json \
		data/definitions-latin-gb.json data/definitions-latin-us.json \
		data/patches/patches.jsonl
	@echo "Building supplement pool (in-memory pipeline, one write)..."
	$(RUN) python3 $(SRC_TOOLS)/build_supplement.py

# Deliberately rebuild the committed supplement checkpoint (re-runs the whole
# combine->classify->prune chain — minutes; only when you intend to re-baseline.
# The transforms are deterministic, so it won't drift the pool or orphan patches).
.PHONY: regenerate-supplement-pool
regenerate-supplement-pool:
	rm -f data/supplement-combined-filtered.json
	@$(MAKE) data/supplement-combined-filtered.json

###########################################
# Merged readlex (published by the EDITOR)
###########################################

SUPPLEMENT_DEPS := data/supplement-combined-filtered.json

# readlex.json ($(READLEX_PATH)) is a COMMITTED INPUT with NO recipe — the
# EDITOR is its sole publisher. On Commit the editor daemon derives it
# in-process (the corpus frequency pass over the pre-patch record set, then
# apply_patches over the live basis — patches are the last word) and
# commits+pushes it alongside patches/patches.jsonl, so the published
# artifact is never out of sync with the patches that produced it. Downstream
# targets depend on $(READLEX_PATH) exactly as they depend on the supplement
# checkpoint above: a committed file make never rebuilds.
#
# check-readlex guards that invariant. The editor's Commit publishes
# readlex.json and patches/patches.jsonl together, but a hand-edit once
# advanced the patches alone (data commit b3d434b) and nothing noticed. git
# does not preserve mtimes, so the signal is provenance inside the data clone:
# the last commit touching readlex.json must be at-or-after (ancestor test —
# a lone repair commit to readlex.json is legitimate) the last commit touching
# the patches. A definite STALE fails hard naming the remedy; undecidable
# states (no git / shallow clone / dirty files / no history) skip soft — the
# rule NEVER rebuilds the file, that would create a second publisher. Wired
# order-only into every target whose recipe reads $(READLEX_PATH), so it runs
# there without dirtying their up-to-date checks.
.PHONY: check-readlex
check-readlex:
	@set -eu; \
	if ! git -C data rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
	  echo "check-readlex: skipped — git unavailable or data/ is not a git checkout"; exit 0; \
	fi; \
	if [ "$$(git -C data rev-parse --is-shallow-repository)" = true ]; then \
	  echo "check-readlex: skipped — data/ is a shallow clone, provenance incomplete"; exit 0; \
	fi; \
	dirty=$$(git -C data status --porcelain -- patches/patches.jsonl readlex.json); \
	if [ -n "$$dirty" ]; then \
	  echo "check-readlex: skipped — uncommitted changes in data/, provenance undecidable:"; \
	  echo "$$dirty"; exit 0; \
	fi; \
	last_patches=$$(git -C data log -1 --format=%H -- patches/patches.jsonl 2>/dev/null || true); \
	last_readlex=$$(git -C data log -1 --format=%H -- readlex.json 2>/dev/null || true); \
	if [ -z "$$last_patches" ] || [ -z "$$last_readlex" ]; then \
	  echo "check-readlex: skipped — no commit history for one of the files"; exit 0; \
	fi; \
	if git -C data merge-base --is-ancestor "$$last_patches" "$$last_readlex"; then \
	  echo "✓ readlex.json publish is current with patches/patches.jsonl"; \
	else \
	  status=$$?; \
	  [ "$$status" -eq 1 ] || { echo "check-readlex: skipped — merge-base failed ($$status), provenance undecidable"; exit 0; }; \
	  echo "check-readlex: STALE — patches/patches.jsonl has commits ($$last_patches)" >&2; \
	  echo "  after the last publish of readlex.json ($$last_readlex)." >&2; \
	  echo "  Press Commit in the editor to republish readlex.json; the editor is its" >&2; \
	  echo "  sole publisher — make will NOT rebuild it." >&2; \
	  exit 1; \
	fi

# The frequency corpus is still needed at RUNTIME by the editor (its basis and
# the publish step enrich freq from it), so its lean checkout stays in setup —
# and install-editor installs it to the daemon's runtime path ($(FREQUENCY_CORPUS)
# is defined in common.mk, shared with build-rules/editor.mk).
#
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

# COMMITTED checkpoint (feeds the gap-fill). ORDER-ONLY prerequisites: rebuilt
# only when MISSING, not on incidental mtime churn. rm to re-baseline.
data/definitions-wiktionary.json: | $(SRC_TOOLS)/extract_wiktionary_definitions.py $(READLEX_PATH) $(WIKTIONARY_JSONL) check-readlex
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
supplements: $(READLEX_PATH) check-readlex
	@echo "✓ All supplements and merged readlex up to date"

supplements-from-source: require-shave data/supplement-wordnet-reliable.json data/supplement-wiktionary-reliable.json
	@echo "Re-scoring with full shave..."
	$(RUN) python3 $(SRC_TOOLS)/rescore_supplements.py --full-shave
	@echo "Generating review files..."
	$(RUN) python3 $(SRC_TOOLS)/generate_review_files.py
	@echo "✓ All supplements rebuilt from source"
