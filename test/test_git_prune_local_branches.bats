#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  git init --bare remote.git
  git remote add origin remote.git
}

teardown() {
  git worktree prune
  teardown_repo
}

@test "git_prune_local_branches: prunes orphaned branch" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push -u origin "feature/a"

  # Delete the branch on the remote
  git push origin --delete "feature/a"

  # Prune the remote tracking branch ref
  git fetch -p

  git checkout main

  run git_prune_local_branches
  assert_success

  # The branch should be gone
  run git rev-parse --verify "feature/a"
  assert_failure
}

@test "git_prune_local_branches: does not prune branches with existing upstreams" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push -u origin "feature/a"

  git fetch -p

  run git_prune_local_branches
  assert_success

  # The branch should still be there
  run git rev-parse --verify "feature/a"
  assert_success
}

@test "git_prune_local_branches: handles no orphaned branches" {
  commit "initial"
  run git_prune_local_branches
  assert_success
  assert_output --partial "No orphaned branches to prune"
}

@test "git_prune_local_branches: does not prune branch in use by a worktree" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push -u origin "feature/a"

  git checkout main

  # Create a worktree with the branch checked out
  git worktree add "${BATS_TEST_TMPDIR}/wt" feature/a

  # Delete the branch on the remote
  git push origin --delete "feature/a"
  git fetch -p

  git checkout main

  run git_prune_local_branches
  assert_success

  # The branch should still be there because it's in a worktree
  run git rev-parse --verify "feature/a"
  assert_success

  # Clean up worktree
  rm -rf "${BATS_TEST_TMPDIR}/wt"
  git worktree prune
}

@test "git_prune_local_branches: does not fail on detached HEAD worktree" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push -u origin "feature/a"

  git checkout main

  # Create a worktree and detach its HEAD
  git worktree add "${BATS_TEST_TMPDIR}/wt-detached"
  (cd "${BATS_TEST_TMPDIR}/wt-detached" && git checkout HEAD~0 --detach)

  # Delete the branch on the remote to trigger prune logic
  git push origin --delete "feature/a"
  git fetch -p

  run git_prune_local_branches
  assert_success
  assert_output --partial "feature/a" # Should prune feature/a successfully

  # Clean up worktree
  rm -rf "${BATS_TEST_TMPDIR}/wt-detached"
  git worktree prune
}
