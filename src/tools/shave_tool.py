#!/usr/bin/env python3
"""
Preflight for the external `shave` binary (github.com/Shavian-info/shave).

Seven call sites shell out to a bare `shave` on $PATH — six generators in this
directory plus src/dictionaries/build_definition_caches.py. Four of them wrap
the call in `except (FileNotFoundError, subprocess.TimeoutExpired)` and return
an empty result, which is the right response to a TIMEOUT — one oversized batch
giving up need not abort a multi-minute run — but the wrong response to the
binary being ABSENT. Absent, every batch takes that branch, the run finishes
successfully, and it writes a pool with every shave consultation silently
dropped. Nothing distinguishes that file from a good one.

So the absence is checked ONCE, up front, before any batching begins. Call
require_shave() from the entry point of anything that will reach a shave call
site. The build calls the equivalent make target (`require-shave` in
build-rules/common.mk); this covers running a generator directly, which the
build's check cannot.
"""

import shutil
import sys

SHAVE_BINARY = "shave"

_MISSING_MESSAGE = f"""\
{SHAVE_BINARY}: not found on $PATH.

The supplement generators transliterate Roman to Shavian by shelling out to it.
Most of them treat a failed call as an empty result, so without this check the
run would SUCCEED and write an under-transliterated pool.

Build and install it from https://github.com/Shavian-info/shave.
Note that shave is built against this pipeline's own data/readlex.json — see
README.md, "The bootstrap cycle"."""


def require_shave():
    """Abort unless the `shave` binary is on $PATH."""
    if shutil.which(SHAVE_BINARY) is None:
        sys.exit(_MISSING_MESSAGE)
