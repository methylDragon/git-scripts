#!/usr/bin/env bash

load "helpers/init.bash"

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

@test "git_prune_remote_prefix: deletes remote branches completely merged into the target branch" {
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

  assert_remote_branch_is_missing origin "feature/a"
}

@test "git_prune_remote_prefix: skips unmerged branches on the remote" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push origin "feature/a"

  run git_prune_remote_prefix "feature/"
  assert_success

  assert_remote_branch_exists origin "feature/a"
}

@test "git_prune_remote_prefix: skips gracefully when no remote branches match the given prefix" {
  commit "initial"
  run git_prune_remote_prefix "non-existent/"
  assert_success
  assert_output --partial "No matching remote branches found"
}
