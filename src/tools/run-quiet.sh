#!/bin/bash
# Wrapper script to run commands quietly (suppressing stdout/stderr)
# Used when QUIET=1 is set for troubleshooting parallel builds

"$@" >/dev/null 2>&1
