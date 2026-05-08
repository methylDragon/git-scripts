#!/usr/bin/env bash
# ==============================================================================
# BATS REPO MANAGEMENT HELPERS
#
# Functions to quickly scaffold, tear down, and manipulate Git repositories
# and complex branching structures specifically tailored for the test suite.
# ==============================================================================

# ------------------------------------------------------------------------------
# setup_repo
#
# Generates a uniquely isolated, temporary Git repository for parallel-safe
# testing. Automatically changes the working directory to the new repo.
# ------------------------------------------------------------------------------
setup_repo() {
  REPO_PATH=$(mktemp -d -t bats-git-repo.XXXXXX)
  cd "$REPO_PATH" || exit 1
  git init -b main
  git config --local user.email "test@example.com"
  git config --local user.name "Test User"
}

# ------------------------------------------------------------------------------
# teardown_repo
#
# Forcefully cleans up the temporary repository directory created by setup_repo.
# ------------------------------------------------------------------------------
teardown_repo() {
  rm -rf "$REPO_PATH"
}

# ------------------------------------------------------------------------------
# commit <message>
#
# Creates a distinct file and commits it with the provided message. A timestamp
# is intentionally appended to guarantee each commit hash is unique even if
# the test runs rapidly or repeats messages.
# ------------------------------------------------------------------------------
commit() {
  echo "$1" >"$1.txt"
  git add .
  git commit -m "$1 $(date +%s%3N)"
}

# ------------------------------------------------------------------------------
# setup_remote_repo [remote_name] [remote_dir]
#
# Clones the active repository into a secondary directory and wires it up as
# a mock remote to effectively test network operations (push/pull/fetch).
# ------------------------------------------------------------------------------
setup_remote_repo() {
  local remote_name="${1:-origin}"
  local remote_dir="${2:-remote}"

  git remote add "$remote_name" .
  git clone . "$remote_dir"

  (
    cd "$remote_dir" || exit 1
    git config user.email "test@example.com"
    git config user.name "Test User"
  )

  git remote set-url "$remote_name" "$remote_dir"
}

# ------------------------------------------------------------------------------
# create_complex_branch_structure
#
# Initializes a deeply nested, multi-forking topological branch stack.
# Essential for validating recursive and cross-stack algorithms.
#
# Stack Layout:
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
# ------------------------------------------------------------------------------
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
