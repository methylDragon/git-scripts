#!/usr/bin/env bash

load "test_helper.bash"

# Creates a branch `feature/a` with two commits, `a1` and `a2`.
# `a1` is cherry-picked into `main`.
#
# initial
# ├─ a1' (main)
# └─ a1 ─ a2 (feature/a)
setup() {
  setup_repo
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  local a1_hash
  a1_hash=$(git rev-parse HEAD)
  commit "a2"
  git checkout main
  commit "a1"
}

teardown() {
  teardown_repo
}

@test "_git_find_cut_point: finds the correct cut point" {
  # We expect the cut point to be the commit `a1` on `feature/a`,
  # as it is the first commit that is already in `main`.
  local cut_point
  cut_point=$(_git_find_cut_point "feature/a" "main")
  assert_equal "$cut_point" "$(git rev-parse feature/a~1)"
}
