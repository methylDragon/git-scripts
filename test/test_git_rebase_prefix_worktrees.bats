#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  commit "initial"
}

teardown() {
  rm -rf "${BATS_TEST_TMPDIR}/wt-"*
  teardown_repo
}

@test "git_rebase_prefix: --all-worktrees detaches and reattaches successfully" {
  # Create a branch in the main worktree
  git checkout -b "feature/a"
  commit "a1"

  # Update main and leave feature/a checked out in main worktree?
  # No, let's checkout main so we can create a worktree for feature/b based on feature/a
  git checkout main

  # Create a second worktree
  git worktree add -b "feature/b" "${BATS_TEST_TMPDIR}/wt-rebase" "feature/a"
  (cd "${BATS_TEST_TMPDIR}/wt-rebase" && git config user.email "test@example.com" && git config user.name "Test User" && commit "b1")

  # Leave feature/a checked out in the main worktree to test detachment of current branch
  git checkout "feature/a"

  # Also update main
  git checkout main
  commit "main-update"

  # Actually we need feature/a checked out in main worktree to test detaching
  git checkout "feature/a"

  # Run from the main worktree (which has feature/a checked out)
  run git_rebase_prefix --all-worktrees "feature/" "main"
  assert_success

  # Check that the branch in the main worktree was rebased
  local a_parent
  a_parent=$(git rev-parse "feature/a~1")
  local main_head
  main_head=$(git rev-parse "main")
  assert_equal "$a_parent" "$main_head"

  # Check that the branch in the second worktree was rebased and reattached
  (cd "${BATS_TEST_TMPDIR}/wt-rebase" && \
    local b_parent
    b_parent=$(git rev-parse "feature/b~1")
    local a_head_in_wt
    a_head_in_wt=$(git rev-parse "feature/a")
    assert_equal "$b_parent" "$a_head_in_wt"
    
    local current_branch
    current_branch=$(git branch --show-current)
    assert_equal "$current_branch" "feature/b"
  )
}
