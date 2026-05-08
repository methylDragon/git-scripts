#!/usr/bin/env bash
# ==============================================================================
# BATS TEST ASSERTIONS
#
# Custom declarative assertions built on top of bats-assert and bats-support.
# Designed to maximize readability and clearly state git-specific expectations
# during test execution.
# ==============================================================================

# ------------------------------------------------------------------------------
# assert_current_branch <branch_name>
#
# Asserts that the currently checked-out branch matches the specified name.
#
# Example:
#   git checkout my-feature
#   assert_current_branch "my-feature"  # Passes: HEAD is my-feature
#   assert_current_branch "main"        # Fails: HEAD is my-feature, not main
# ------------------------------------------------------------------------------
assert_current_branch() {
  local expected_branch="$1"
  local current_branch
  current_branch=$(git branch --show-current)
  assert_equal "$expected_branch" "$current_branch" "Expected to be on branch '$expected_branch', but currently on '$current_branch'"
}

# ------------------------------------------------------------------------------
# assert_branch_is_immediate_parent_of <parent_branch> <child_branch>
#
# Asserts that the child branch's immediate parent (HEAD~1) exactly matches
# the parent branch's HEAD commit. Useful for verifying topology post-rebase.
#
# Example Stack Layout:
# main
# └── feature/a
#     └── feature/a-b (parent_branch)
#         └── feature/a-b-c (child_branch)
#
# Example:
#   assert_branch_is_immediate_parent_of "feature/a-b" "feature/a-b-c"  # Passes: a-b-c~1 is a-b
#   assert_branch_is_immediate_parent_of "main" "feature/a-b-c"         # Fails: a-b-c~1 is a-b, not main
# ------------------------------------------------------------------------------
assert_branch_is_immediate_parent_of() {
  local parent_branch="$1"
  local child_branch="$2"

  local parent_hash
  parent_hash=$(git rev-parse "$parent_branch")

  local actual_parent_hash
  actual_parent_hash=$(git rev-parse "$child_branch~1")

  assert_equal "$parent_hash" "$actual_parent_hash" "Expected parent of '$child_branch' to be '$parent_branch'"
}

# ------------------------------------------------------------------------------
# assert_local_branch_exists <branch_name>
#
# Asserts that a branch with the specified name exists in the local repository.
#
# Example Stack Layout:
# main
# └── feature/a
#
# Example:
#   assert_local_branch_exists "feature/a"  # Passes: feature/a is checked out or exists locally
#   assert_local_branch_exists "feature/b"  # Fails: feature/b was never created locally
# ------------------------------------------------------------------------------
assert_local_branch_exists() {
  local branch="$1"
  run git rev-parse --verify "$branch"
  assert_success "Expected local branch '$branch' to exist"
}

# ------------------------------------------------------------------------------
# assert_local_branch_is_missing <branch_name>
#
# Asserts that a branch with the specified name does not exist locally.
#
# Example Stack Layout:
# main
# (feature/a is deleted or never created)
#
# Example:
#   assert_local_branch_is_missing "feature/a"  # Passes: feature/a does not exist
#   assert_local_branch_is_missing "main"       # Fails: main exists
# ------------------------------------------------------------------------------
assert_local_branch_is_missing() {
  local branch="$1"
  run git rev-parse --verify "$branch"
  assert_failure "Expected local branch '$branch' to be missing"
}

# ------------------------------------------------------------------------------
# assert_remote_branch_exists <remote_name> <branch_name>
#
# Connects to the given remote and asserts the branch is published there.
#
# Example Stack Layout:
# origin/main
# └── origin/feature/a
#
# Example:
#   assert_remote_branch_exists "origin" "feature/a"  # Passes: feature/a was pushed
#   assert_remote_branch_exists "origin" "feature/b"  # Fails: feature/b was never pushed
# ------------------------------------------------------------------------------
assert_remote_branch_exists() {
  local remote="$1"
  local branch="$2"
  run git ls-remote --heads "$remote" "$branch"
  assert_output --partial "refs/heads/$branch"
}

# ------------------------------------------------------------------------------
# assert_remote_branch_is_missing <remote_name> <branch_name>
#
# Connects to the given remote and asserts the branch has been pruned/deleted.
#
# Example Stack Layout:
# origin/main
# (origin/feature/a is deleted or never pushed)
#
# Example:
#   assert_remote_branch_is_missing "origin" "feature/a"  # Passes: branch absent on remote
#   assert_remote_branch_is_missing "origin" "main"       # Fails: branch exists on remote
# ------------------------------------------------------------------------------
assert_remote_branch_is_missing() {
  local remote="$1"
  local branch="$2"
  run git ls-remote --heads "$remote" "$branch"
  assert_output ""
}

# ------------------------------------------------------------------------------
# assert_branches_point_to_same_commit <branch_a> <branch_b>
#
# Asserts that two branches (or references, like HEAD and origin/main)
# currently point to the exact same commit hash.
#
# Example Stack Layout:
# Commit: c1a2b3c (main)
# └── Commit: d4e5f6g (feature/a, feature/b)
#     (Both branches reference the identical commit hash)
#
# Example:
#   assert_branches_point_to_same_commit "feature/a" "feature/b"  # Passes: both point to d4e5f6g
#   assert_branches_point_to_same_commit "main" "feature/a"       # Fails: main points to c1a2b3c
# ------------------------------------------------------------------------------
assert_branches_point_to_same_commit() {
  local branch_a="$1"
  local branch_b="$2"

  local hash_a
  hash_a=$(git rev-parse "$branch_a")

  local hash_b
  hash_b=$(git rev-parse "$branch_b")

  assert_equal "$hash_a" "$hash_b" "Expected '$branch_a' and '$branch_b' to point to the same commit"
}

# ------------------------------------------------------------------------------
# assert_pushed_branch_matches_local <bare_repo_path> <branch_name>
#
# Asserts that a specific branch inside a bare remote repository points to
# the exact same commit as the local counterpart. Useful for verifying pushes.
#
# Example Stack Layout:
# main
# └── feature/a (HEAD, remote.git:feature/a)
#
# Example:
#   assert_pushed_branch_matches_local "remote.git" "feature/a"  # Passes: local and remote match
#   assert_pushed_branch_matches_local "remote.git" "main"       # Fails: local and remote out of sync
# ------------------------------------------------------------------------------
assert_pushed_branch_matches_local() {
  local bare_repo="$1"
  local branch="$2"

  local remote_hash
  remote_hash=$(git --git-dir="$bare_repo" rev-parse "$branch")

  local local_hash
  local_hash=$(git rev-parse "$branch")

  assert_equal "$remote_hash" "$local_hash" "Expected remote '$bare_repo' to have the same commit for '$branch' as local"
}
