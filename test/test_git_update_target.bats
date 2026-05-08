#!/usr/bin/env bash

load "helpers/init.bash"

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
  assert_current_branch "feature/a"
}

@test "_git_update_target: handles local-only branch" {
  commit "initial"
  run _git_update_target "main"
  assert_success
  assert_output --partial "'main' is local-only (no upstream)"
}

@test "_git_update_target: pulls updates from upstream" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git checkout main
  git merge "feature/a"

  # Set up a remote
  setup_remote_repo origin remote
  (cd remote && git checkout -b feature/b && commit "b1" && git checkout main && git merge "feature/b")
  git fetch origin
  git branch --set-upstream-to=origin/main main

  # Make local main behind remote main
  git reset --hard HEAD~1

  run _git_update_target "main"
  assert_success
  assert_output --partial "Pulling updates"
  assert_branches_point_to_same_commit "HEAD" "origin/main"
}

@test "_git_update_target: fetches remote tracking branch when target is locked in another worktree" {
  commit "initial"
  git checkout -b "feature/a"
  commit "a1"
  git checkout main
  git merge "feature/a"

  # Set up a remote
  setup_remote_repo origin remote
  (cd remote && git checkout -b feature/b && commit "b1" && git checkout main && git merge "feature/b")
  git fetch origin
  git branch --set-upstream-to=origin/main main

  # Checkout a different branch in main worktree so we can test updating 'main'
  git checkout -b "feature/test"

  # Lock main in another worktree
  git worktree add "${BATS_TEST_TMPDIR}/wt-locked" main

  run _git_update_target "main"
  assert_success
  assert_output --partial "Target branch 'main' is in another worktree. Fetching its remote tracking branch instead."

  # Verify the remote tracking branch was fetched and has the new commit
  local remote_hash
  remote_hash=$(git rev-parse origin/main)
  local remote_upstream_hash
  remote_upstream_hash=$(cd remote && git rev-parse main)
  assert_equal "$remote_hash" "$remote_upstream_hash" "Expected origin/main to match the actual remote repo's main branch"

  # Cleanup
  rm -rf "${BATS_TEST_TMPDIR}/wt-locked"
  git worktree prune
}
