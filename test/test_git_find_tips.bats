#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  create_complex_branch_structure
}

teardown() {
  teardown_repo
}

@test "_git_find_tips: finds the correct tips" {
  local all_branches=($(git for-each-ref --format='%(refname:short)' "refs/heads/test-chain-*"))
  local tips=$(_git_find_tips "${all_branches[@]}")
  local expected_tips="test-chain-a-b-c
test-chain-d-e-f-g-h-i
test-chain-d-e-f-j-k-l"
  assert_equal "$tips" "$expected_tips"
}
