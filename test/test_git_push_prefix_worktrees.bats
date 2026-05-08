#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  commit "initial"
  git init --bare "${BATS_TEST_TMPDIR}/remote.git"
  git remote add origin "${BATS_TEST_TMPDIR}/remote.git"
  git push -u origin main
}

teardown() {
  rm -rf "${BATS_TEST_TMPDIR}/wt-"*
  rm -rf "${BATS_TEST_TMPDIR}/remote.git"
  teardown_repo
}

@test "git_push_prefix: pushes branches even if checked out in other worktrees" {
  # Create a branch in the main worktree
  git checkout -b "feature/a"
  commit "a1"

  # Create a second worktree and a branch in it
  git worktree add "${BATS_TEST_TMPDIR}/wt-push-test"
  (cd "${BATS_TEST_TMPDIR}/wt-push-test" && git config user.email "test@example.com" && git config user.name "Test User" && git checkout -b "feature/b" && commit "b1")

  # Update main
  git checkout main

  # Run from the main worktree (no --all-worktrees needed!)
  run git_push_prefix "feature/"
  assert_success

  # Check that both branches were pushed to the remote
  local remote_branches
  remote_branches=$(git --git-dir="${BATS_TEST_TMPDIR}/remote.git" branch)
  assert_output --partial "feature/a" <<< "$remote_branches"
  assert_output --partial "feature/b" <<< "$remote_branches"
}
