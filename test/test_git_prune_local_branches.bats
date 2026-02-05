#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  git init --bare remote.git
  git remote add origin remote.git
}

teardown() {
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
  assert_output --partial "No orphaned branches found"
}
