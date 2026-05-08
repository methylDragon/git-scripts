#!/usr/bin/env bash

load "helpers/init.bash"

setup() {
  setup_repo
  # Set up a remote pointing to a bare repo
  git init --bare remote.git
  git remote add origin remote.git
}

teardown() {
  teardown_repo
}

@test "git_push_prefix: pushes newly created branches to the remote" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git checkout -b "feature/b"
  commit "b1"

  # No mock needed for this, we can inspect the result on the remote
  run git_push_prefix "feature/"
  assert_success

  local remote_branches
  remote_branches=$(git --git-dir=remote.git branch)
  assert_output --partial "feature/a" <<<"$remote_branches"
  assert_output --partial "feature/b" <<<"$remote_branches"
}

@test "git_push_prefix: skips pushing branches that are already up-to-date with the remote" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push origin "feature/a"

  # Mock git push to fail if it's called
  git() {
    if [[ $1 == "push" ]]; then
      echo "git push should not be called" >&2
      return 1 # Fail the test
    else
      command git "$@"
    fi
  }
  export -f git

  run git_push_prefix "feature/"
  assert_success
  assert_output --partial "All matched branches (1) are already up-to-date"
}

@test "git_push_prefix: pushes branches containing new local commits" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git push origin "feature/a"
  commit "a2"

  run git_push_prefix "feature/"
  assert_success

  assert_pushed_branch_matches_local "remote.git" "feature/a"
}

@test "git_push_prefix: gracefully completes when no branches match the given prefix" {
  commit "initial"
  run git_push_prefix "non-existent/"
  assert_success
  assert_output --partial "No matching branches found"
}
