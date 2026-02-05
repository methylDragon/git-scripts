#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  commit "initial"
  git init --bare remote.git
  git remote add origin remote.git
  git push -u origin main
}

teardown() {
  teardown_repo
}

@test "git_prune_remote_prefix: prunes merged remote branch" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push origin "feature/a"

  # Merge the branch into main
  git checkout main
  git merge "feature/a"
  git push origin main

  run git_prune_remote_prefix "feature/"
  assert_success

  # The remote branch should be gone
  run git ls-remote --exit-code origin "refs/heads/feature/a"
  assert_failure
}

@test "git_prune_remote_prefix: does not prune unmerged remote branches" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push origin "feature/a"

  run git_prune_remote_prefix "feature/"
  assert_success

  # The remote branch should still be there
  run git ls-remote --exit-code origin "refs/heads/feature/a"
  assert_success
}

@test "git_prune_remote_prefix: handles no matching branches" {
  commit "initial"
  run git_prune_remote_prefix "non-existent/"
  assert_success
  assert_output --partial "No matching remote branches found"
}
