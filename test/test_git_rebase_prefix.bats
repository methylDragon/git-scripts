#!/usr/bin/env bash

load "test_helper.bash"

# Create a complex branch structure for testing:
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
#
setup() {
  setup_repo
  create_complex_branch_structure
}

teardown() {
  teardown_repo
}

@test "git_rebase_prefix: rebases linear and forking stacks" {
  # We expect that git_rebase_prefix will identify the three tips of the stacks
  # (test-chain-a-b-c, test-chain-d-e-f-g-h-i, and test-chain-d-e-f-j-k-l)
  # and rebase them onto main. The --update-refs flag should ensure that the
  # entire stack is moved correctly.

  local before
  before=$(git log --all --decorate --oneline --graph)

  commit "main-update"
  git_rebase_prefix "test-chain-" "main"

  local after
  after=$(git log --all --decorate --oneline --graph)

  echo "--- Before Rebase ---"
  echo "$before"
  echo "--- After Rebase ---"
  echo "$after"
  echo "---------------------"

  # We expect the 'a' stack to be a simple linear rebase.
  # test-chain-a-b should now be based on test-chain-a, and so on.
  assert_parent "$(git rev-parse --short main)" "test-chain-a"
  assert_parent "$(git rev-parse --short test-chain-a)" "test-chain-a-b"
  assert_parent "$(git rev-parse --short test-chain-a-b)" "test-chain-a-b-c"

  # We expect the 'd' stack to have been rebased linearly up to the fork point.
  assert_parent "$(git rev-parse --short main)" "test-chain-d"
  assert_parent "$(git rev-parse --short test-chain-d)" "test-chain-d-e"
  assert_parent "$(git rev-parse --short test-chain-d-e)" "test-chain-d-e-f"

  # We expect the first fork 'g' to be rebased on top of the new 'f'.
  assert_parent "$(git rev-parse --short test-chain-d-e-f)" "test-chain-d-e-f-g"
  assert_parent "$(git rev-parse --short test-chain-d-e-f-g)" "test-chain-d-e-f-g-h"
  assert_parent "$(git rev-parse --short test-chain-d-e-f-g-h)" "test-chain-d-e-f-g-h-i"

  # We expect the second fork 'j' to also be rebased on top of the new 'f'.
  assert_parent "$(git rev-parse --short test-chain-d-e-f)" "test-chain-d-e-f-j"
  assert_parent "$(git rev-parse --short test-chain-d-e-f-j)" "test-chain-d-e-f-j-k"
  assert_parent "$(git rev-parse --short test-chain-d-e-f-j-k)" "test-chain-d-e-f-j-k-l"
}

@test "git_rebase_prefix: handles rebase conflicts" {
  # Create a conflict.
  git checkout -b "conflict-branch"
  echo "conflict" > conflict.txt
  git add conflict.txt
  git commit -m "conflict1"
  git checkout main
  echo "different" > conflict.txt
  git add conflict.txt
  git commit -m "conflict2"

  # Run the rebase and expect it to fail.
  run git_rebase_prefix "conflict-" "main"
  assert_failure
}

@test "git_rebase_prefix: handles empty prefix" {
  run git_rebase_prefix "" "main"
  assert_failure
  assert_output --partial "Error: Missing <prefix>"
}

@test "git_rebase_prefix: handles no matching branches" {
  run git_rebase_prefix "no-match-" "main"
  assert_success
  assert_output --partial "No matching branches found"
}
