#!/usr/bin/env bash

load "helpers/init.bash"

setup() {
  setup_repo
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  local old_hash
  old_hash=$(git rev-parse HEAD)
  git checkout -b "feature/b"
  commit "b1"
  git checkout -b "feature/c"
  commit "c1"
  git checkout "feature/a"
  git reset --hard "$old_hash"
  git commit --amend -m "a2"
}

teardown() {
  teardown_repo
}

@test "git_evolve: rebases orphaned children" {
  local old_hash
  old_hash=$(git rev-parse "HEAD@{1}")
  git_evolve "$old_hash" <<<"y"
  assert_branch_is_immediate_parent_of "feature/a" "feature/b"
  assert_branch_is_immediate_parent_of "feature/b" "feature/c"
}
