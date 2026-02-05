#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
}

teardown() {
  teardown_repo
}

@test "_git_is_obsolete: detects cherry-picked commits" {
  # main
  # └─ initial
  #    └─ a1
  #
  # feature/a
  # └─ initial
  #    └─ a1
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  local a1_hash=$(git rev-parse HEAD)
  git checkout main
  git cherry-pick "$a1_hash"

  run _git_is_obsolete "$a1_hash" "main"
  assert_success
}

@test "_git_is_obsolete: detects rebased commits" {
  # main
  # └─ initial
  #    └─ main-update
  #
  # feature/a
  # └─ initial
  #    └─ a1
  #
  # After rebase and merge:
  # main
  # └─ initial
  #    └─ main-update
  #       └─ a1' <-- feature/a
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git checkout main
  commit "main-update"
  git checkout "feature/a"
  git rebase main

  git checkout main
  git merge "feature/a"
  run _git_is_obsolete "feature/a" "main"
  assert_success
}

@test "_git_is_obsolete: detects reverted commits" {
  # main
  # └─ initial
  #    └─ a1
  #
  # feature/a
  # └─ initial
  #    ├─ a1
  #    └─ revert a1
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  local a1_hash=$(git rev-parse HEAD)
  git revert "$a1_hash" --no-edit
  git checkout main
  git cherry-pick "$a1_hash"

  run _git_is_obsolete "feature/a" "main"
  assert_success
}

@test "_git_is_obsolete: detects squash-merged commits" {
  # main
  # └─ initial
  #    └─ a1+a2 (squashed)
  #
  # feature/a
  # └─ initial
  #    ├─ a1
  #    └─ a2
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  commit "a2"

  git checkout main
  git merge --squash "feature/a"
  git commit -m "squash a1 and a2"

  run _git_is_obsolete "feature/a" "main"
  assert_success
}
