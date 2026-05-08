#!/usr/bin/env bash
# ==============================================================================
# BATS TEST INITIALIZATION
#
# Primary entry point for the test suite. Loads all upstream dependencies
# (bats-support, bats-assert), sources the core utility script being tested,
# and bootstraps the internal helper library (repo_management, assertions).
# ==============================================================================

# Load external Bats utilities
load "deps/bats-support/load.bash"
load "deps/bats-assert/load.bash"

# Source the target script (the actual Git stack functions)
source "git_bash_functions.sh"

# Dynamically load internal helpers relative to this init script
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${DIR}/repo_management.bash"
source "${DIR}/assertions.bash"
