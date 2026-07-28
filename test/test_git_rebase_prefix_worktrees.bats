#!/usr/bin/env bash

load "helpers/init.bash"

setup() {
  setup_repo
  commit "initial"
}

teardown() {
  rm -rf "${BATS_TEST_TMPDIR}/wt-"*
  teardown_repo
}

@test "git_rebase_prefix: --all-worktrees successfully detaches, rebases, and reattaches multiple worktrees" {
  # Create a branch in the main worktree
  git checkout -b "feature/a"
  commit "a1"

  # Checkout main so we can create a secondary worktree for feature/b
  git checkout main

  # Create a second worktree
  git worktree add -b "feature/b" "${BATS_TEST_TMPDIR}/wt-rebase" "feature/a"
  (cd "${BATS_TEST_TMPDIR}/wt-rebase" && git config user.email "test@example.com" && git config user.name "Test User" && commit "b1")

  # Update main to provide a new base for the rebase
  git checkout main
  commit "main-update"

  # Keep feature/a checked out in the main worktree to test detachment of the current branch
  git checkout "feature/a"

  # Run from the main worktree (which has feature/a checked out)
  run git_rebase_prefix --all-worktrees "feature/" "main"
  assert_success

  # Check that the branch in the main worktree was rebased
  assert_branch_is_immediate_parent_of "main" "feature/a"

  # Check that the branch in the second worktree was rebased and correctly reattached
  (
    cd "${BATS_TEST_TMPDIR}/wt-rebase" || exit 1
    assert_branch_is_immediate_parent_of "feature/a" "feature/b"

    local current_branch
    current_branch=$(git branch --show-current)
    assert_equal "$current_branch" "feature/b"
  )
}

@test "git_rebase_prefix: --all-worktrees aborts rebase on conflict and safely reattaches worktree" {
  git checkout -b "feature/conflict"
  echo "conflict" >conflict.txt
  git add conflict.txt
  commit "conflict1"

  git checkout main
  echo "different" >conflict.txt
  git add conflict.txt
  commit "conflict2"

  git worktree add "${BATS_TEST_TMPDIR}/wt-conflict" "feature/conflict"

  # Run from main worktree (main branch)
  run git_rebase_prefix --all-worktrees "feature/" "main"
  assert_failure
  assert_output --partial "Conflict. Aborting"

  # Check that it reattached
  (
    cd "${BATS_TEST_TMPDIR}/wt-conflict" &&
      local current_branch
    current_branch=$(git branch --show-current)
    assert_equal "$current_branch" "feature/conflict"
  )
}

@test "git_rebase_prefix: --all-worktrees gracefully skips worktrees with active merge conflicts" {
  git checkout -b "feature/busy1"
  commit "busy1"
  git checkout main

  git checkout -b "feature/busy2"
  commit "busy2"
  git checkout main

  git checkout -b "feature/busy3"
  echo "merge-conflict" >file.txt
  git add file.txt
  commit "unrelated1"
  git checkout main

  echo "merge-conflict-main" >file.txt
  git add file.txt
  commit "main1"

  git worktree add "${BATS_TEST_TMPDIR}/wt-busy" "feature/busy3"

  # Make the worktree busy with a merge conflict
  (
    cd "${BATS_TEST_TMPDIR}/wt-busy" &&
      git merge main || true
  )

  git worktree add "${BATS_TEST_TMPDIR}/wt-feature" "feature/busy1"

  git checkout main
  commit "main-update"

  # Run from main worktree
  run git_rebase_prefix --all-worktrees "feature/" "main"
  assert_failure

  # It should skip the busy worktree during detach
  assert_output --partial "Warning: Worktree '${BATS_TEST_TMPDIR}/wt-busy' is busy. Skipping detach"

  # Check rebase succeeded for feature
  assert_branch_is_immediate_parent_of "main" "feature/busy1"
}

@test "git_rebase_prefix: --all-worktrees completes rebase but gracefully skips reattaching if blocked by untracked files" {
  git checkout -b "feature/unstaged"
  echo "a" >feature.txt
  git add feature.txt
  commit "a"

  git checkout main
  echo "b" >main-file.txt
  git add main-file.txt
  commit "main-update"

  git worktree add "${BATS_TEST_TMPDIR}/wt-unstaged" "feature/unstaged"

  # Create a conflicting unstaged state in the worktree.
  # The updated `main` branch introduces `main-file.txt`. The rebase will apply this commit.
  # By creating an untracked file named `main-file.txt` in the worktree, the reattach
  # process (git checkout) will fail, as it would overwrite the untracked file.
  (
    cd "${BATS_TEST_TMPDIR}/wt-unstaged" &&
      echo "conflict" >main-file.txt
  )

  run git_rebase_prefix --all-worktrees "feature/" "main"
  assert_success

  # Ensure the detach/reattach engine caught the reattach failure and warned the user
  assert_output --partial "Could not re-attach 'feature/unstaged' in '${BATS_TEST_TMPDIR}/wt-unstaged'"

  # Rebase should still be successful regardless of the reattach failure
  assert_branch_is_immediate_parent_of "main" "feature/unstaged"

  # Verify the worktree is safely left in a detached HEAD state to preserve local files
  (
    cd "${BATS_TEST_TMPDIR}/wt-unstaged" &&
      local current_branch
    current_branch=$(git branch --show-current)
    assert_equal "$current_branch" ""
  )
}

@test "git_rebase_prefix: skips stack if a branch is in another worktree and --all-worktrees is omitted" {
  git checkout -b "feature/skip_tip"
  commit "skip_tip_1"

  git checkout -b "feature/skip_child"
  commit "skip_child_1"

  git checkout main
  commit "main_update"

  # Add parent branch to a worktree
  git worktree add "${BATS_TEST_TMPDIR}/wt-skip" "feature/skip_tip"

  run git_rebase_prefix "feature/" "main"
  assert_failure

  # It should warn about skip_tip
  assert_output --partial "Warning: Branch 'feature/skip_tip' in stack is checked out in another worktree."
  assert_output --partial "Skipping stack. (Use --all-worktrees to automatically rebase across worktrees)"

  # Neither should be rebased onto the new main commit
  # The parent branch should not have the main_update commit in its history
  run git merge-base main feature/skip_tip
  local initial_commit
  initial_commit=$(git rev-parse HEAD~1) # initial commit is HEAD~1 of main
  assert_output "$initial_commit"
}
