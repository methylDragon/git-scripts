#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
}

teardown() {
  teardown_repo
}

@test "_git_update_target: target branch does not exist" {
  run _git_update_target "non-existent-branch"
  assert_failure
  assert_output --partial "Target branch 'non-existent-branch' does not exist locally"
}

@test "_git_update_target: switches to target branch" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git checkout main

  run _git_update_target "feature/a"
  assert_success
  local current_branch=$(git branch --show-current)
  assert_equal "$current_branch" "feature/a"
}

@test "_git_update_target: handles local-only branch" {
  commit "initial"
  run _git_update_target "main"
  assert_success
  assert_output --partial "'main' is local-only (no upstream)"
}

@test "_git_update_target: pulls updates from upstream" {
  # Set up a remote
  git remote add origin .
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git checkout main
  git merge "feature/a"

  # Clone to a separate directory to simulate a remote
  git clone . remote
  (cd remote && git config user.email "test@example.com" && git config user.name "Test User" && git checkout -b feature/b && commit "b1" && git checkout main && git merge "feature/b")

  # Set up upstream for main
  git remote set-url origin remote
  git fetch origin
  git branch --set-upstream-to=origin/main main

  # Make local main behind remote main
  git reset --hard HEAD~1

  run _git_update_target "main"
  assert_success
  assert_output --partial "Pulling updates"
  local local_hash=$(git rev-parse HEAD)
  local remote_hash=$(git rev-parse origin/main)
  assert_equal "$local_hash" "$remote_hash"
}
