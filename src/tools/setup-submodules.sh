#!/usr/bin/env bash
#
# Initialise git submodules, checking out frequency-words lean.
#
# frequency-words (hermitdave/FrequencyWords) ships every language, ~1.4 GB.
# We use exactly one file: content/2018/en/en_full.txt. A plain
# `git submodule update --init` would materialise the whole thing, and even a
# blobless filter followed by a sparse prune leaves the fetched blobs behind in
# .git. The only genuinely lean path is: clone the submodule git dir WITHOUT a
# checkout, set a cone sparse-checkout, THEN check out — so the pruned blobs are
# never fetched. Result: ~30 MB instead of ~1.4 GB.
#
# Re-runnable: safe to run on a fresh clone or an already-populated tree.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

LEAN_SUBMODULE="external/frequency-words"
LEAN_SPARSE_PATH="content/2018/en"

# Everything except the lean submodule: standard init.
git submodule update --init --recursive --depth 1 \
  $(git config -f .gitmodules --get-regexp '^submodule\..*\.path$' \
      | awk '{print $2}' | grep -vx "$LEAN_SUBMODULE")

setup_lean_submodule() {
  local path="$1" sparse="$2"
  local url gitdir sha
  gitdir=".git/modules/${path}"
  sha="$(git ls-tree HEAD "$path" | awk '{print $3}')"

  if [ -z "$sha" ]; then
    echo "error: ${path} is not a committed submodule in this repo" >&2
    exit 1
  fi

  # Sparse path already materialised? Nothing to do.
  if [ -d "${path}/${sparse}" ] && [ -n "$(ls -A "${path}/${sparse}" 2>/dev/null)" ]; then
    echo "${path}: already checked out"
    return
  fi

  # Fresh state so the no-checkout clone owns the git dir.
  git submodule deinit -f "$path" >/dev/null 2>&1 || true
  rm -rf "$gitdir" "${path:?}"

  # Register url/active in .git/config so `git submodule status` sees it.
  git submodule init "$path"
  url="$(git config "submodule.${path}.url")"

  echo "${path}: lean clone (sparse: ${sparse})"
  mkdir -p "$path"
  git clone --no-checkout --filter=blob:none --depth 1 --single-branch \
    --separate-git-dir="$gitdir" "$url" "$path"
  git -C "$path" sparse-checkout init --cone
  git -C "$path" sparse-checkout set "$sparse"
  git -C "$path" checkout --detach "$sha"
}

setup_lean_submodule "$LEAN_SUBMODULE" "$LEAN_SPARSE_PATH"

echo "Submodules ready."
