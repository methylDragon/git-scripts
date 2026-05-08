#!/usr/bin/env bash

load "helpers/init.bash"

setup() {
  setup_repo
}

teardown() {
  git worktree prune
  teardown_repo
}

@test "_git_is_in_another_worktree: safely handles branch names with regex characters" {
  commit "initial"

  # Create a branch with regex characters that are valid in git: + . ( ) | $
  local branch_name="feature/regex(a).+|"

  git checkout -b "$branch_name"
  commit "regex-commit"

  git checkout main

  # Add it to a worktree
  git worktree add "${BATS_TEST_TMPDIR}/wt-regex" "$branch_name"

  run _git_is_in_another_worktree "$branch_name"
  assert_success # 0 exit code means it IS in another worktree

  # Cleanup
  rm -rf "${BATS_TEST_TMPDIR}/wt-regex"
}

@test "_git_is_in_another_worktree: safely handles .git path overlaps" {
  commit "initial"

  local branch_name="feature/test"
  git checkout -b "$branch_name"

  git checkout main

  # Do NOT add it to a worktree, but name the worktree something that might collide with .git
  git worktree add "${BATS_TEST_TMPDIR}/.git-worktree" -b some-other-branch

  # Check our feature branch
  run _git_is_in_another_worktree "$branch_name"
  assert_failure # 1 exit code means it is NOT in another worktree

  # Cleanup
  rm -rf "${BATS_TEST_TMPDIR}/.git-worktree"
}
