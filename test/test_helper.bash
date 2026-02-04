#!/usr/bin/env bash

# Load Bats Support, Assert, and an alias for `run`
load "deps/bats-support/load.bash"
load "deps/bats-assert/load.bash"

# Source the functions we're testing
source "git_bash_functions.sh"

# ------------------------------------------------------------------------------
# TEST HELPERS
# ------------------------------------------------------------------------------

# Creates a temporary git repository for testing.
#
# Usage:
#   setup_repo
#
# This will create a new directory in the bats temporary directory,
# initialize a git repository in it, and cd into it.
#
# The path to the repository is stored in the global variable REPO_PATH.
setup_repo() {
  REPO_PATH=$(mktemp -d -t bats-git-repo.XXXXXX)
  cd "$REPO_PATH"
  git init -b main
  git config --local user.email "test@example.com"
  git config --local user.name "Test User"
}

# Cleans up the temporary git repository.
#
# Usage:
#   teardown_repo
#
# This will remove the temporary directory created by setup_repo.
teardown_repo() {
  rm -rf "$REPO_PATH"
}

# Creates a commit with a given message.
#
# Usage:
#   commit <message>
#
# This will create a new file with the message as its content and commit it.
commit() {
  echo "$1" > "$1.txt"
  git add .
  # Timestamp to keep the commits distinct
  git commit -m "$1 $(date +%s%3N)"
}

assert_parent() {
  local parent="$1"
  local child="$2"
  local actual_parent
  actual_parent=$(git rev-parse --short "$child~1")
  assert_equal "$parent" "$actual_parent" "parent of $child should be $parent"
}

# Creates a complex branch structure with forks for testing:
#
# main
# ├── test-chain-a
# │   └── test-chain-a-b
# │       └── test-chain-a-b-c
# └── test-chain-d
#     └── test-chain-d-e
#         └── test-chain-d-e-f
#             ├── test-chain-d-e-f-g
#             │   └── test-chain-d-e-f-g-h
#             │       └── test-chain-d-e-f-g-h-i
#             └── test-chain-d-e-f-j
#                 └── test-chain-d-e-f-j-k
#                     └── test-chain-d-e-f-j-k-l
create_complex_branch_structure() {
  commit "initial"
  git checkout -b "test-chain-a"
  commit "a"
  git checkout -b "test-chain-a-b"
  commit "b"
  git checkout -b "test-chain-a-b-c"
  commit "c"

  git checkout main
  git checkout -b "test-chain-d"
  commit "d"
  git checkout -b "test-chain-d-e"
  commit "e"
  git checkout -b "test-chain-d-e-f"
  commit "f"

  git checkout "test-chain-d-e-f"
  git checkout -b "test-chain-d-e-f-g"
  commit "g"
  git checkout -b "test-chain-d-e-f-g-h"
  commit "h"
  git checkout -b "test-chain-d-e-f-g-h-i"
  commit "i"

  git checkout "test-chain-d-e-f"
  git checkout -b "test-chain-d-e-f-j"
  commit "j"
  git checkout -b "test-chain-d-e-f-j-k"
  commit "k"
  git checkout -b "test-chain-d-e-f-j-k-l"
  commit "l"

  git checkout main
}
