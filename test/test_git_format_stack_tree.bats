#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  create_complex_branch_structure
}

teardown() {
  teardown_repo
}

@test "_git_format_stack_tree: formats a simple stack" {
  local expected_output="test-chain-a-b-c
    ├─ test-chain-a-b
    └─ test-chain-a"

  run _git_format_stack_tree "test-chain-a-b-c" "test-chain-" "main" "false"
  assert_success
  assert_output "$expected_output"
}

@test "_git_format_stack_tree: formats a complex forking stack" {
  local tip="test-chain-d-e-f-g-h-i"
  local allowed_refs="test-chain-d-e-f-g-h-i test-chain-d-e-f-g-h test-chain-d-e-f-g test-chain-d-e-f test-chain-d-e test-chain-d"
  local expected_output="test-chain-d-e-f-g-h-i
    ├─ test-chain-d-e-f-g-h
    ├─ test-chain-d-e-f-g
    ├─ test-chain-d-e-f
    ├─ test-chain-d-e
    └─ test-chain-d"

  run _git_format_stack_tree "$tip" "test-chain-" "main" "false" "$allowed_refs"
  assert_success
  assert_output "$expected_output"
}

@test "_git_format_stack_tree: filters merged branches" {
  # Merge 'test-chain-a' into main
  git checkout main
  git merge --ff-only "test-chain-a"

  local expected_output="test-chain-a-b-c
    └─ test-chain-a-b"

  run _git_format_stack_tree "test-chain-a-b-c" "test-chain-" "main" "true"
  assert_success
  assert_output "$expected_output"
}
