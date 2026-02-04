#!/usr/bin/env bash

load "test_helper.bash"

setup() {
  setup_repo
  create_complex_branch_structure
}

teardown() {
  teardown_repo
}

@test "_git_find_sync_point: finds the correct sync point in a forking stack" {
  # Start with a complex tree structure.
  #
  # main
  # ├── test-chain-a
  # │   └── test-chain-a-b
  # │       └── test-chain-a-b-c
  # └── test-chain-d
  #     └── test-chain-d-e
  #         └── test-chain-d-e-f
  #             ├── test-chain-d-e-f-g
  #             │   └── test-chain-d-e-f-g-h
  #             │       └── test-chain-d-e-f-g-h-i
  #             └── test-chain-d-e-f-j
  #                 └── test-chain-d-e-f-j-k
  #                     └── test-chain-d-e-f-j-k-l
  #
  local all_branches=($(git for-each-ref --format='%(refname:short)' "refs/heads/test-chain-*"))
  declare -A initial_ref_map
  for branch in "${all_branches[@]}"; do
    initial_ref_map["$branch"]=$(git rev-parse "$branch")
  done

  # Rebase one of the forks, which will duplicate the common history.
  #
  # main
  # ├── test-chain-d' -> e' -> f' -> g' -> h' -> i'
  # │   └── ...
  # └── test-chain-d
  #     └── test-chain-d-e
  #         └── test-chain-d-e-f  <-- copied, sync point for test-chain-d-e-f-j-k-l
  #             ├── test-chain-d-e-f-g
  #             │   └── ...
  #             └── test-chain-d-e-f-j
  #                 └── ...
  #
  git checkout main
  commit "main-update"
  git checkout test-chain-d-e-f-g-h-i
  git rebase --update-refs main

  cd "$REPO_PATH"
  git log --graph --oneline --all
  local sync_point
  sync_point=$(_git_find_sync_point "test-chain-d-e-f-j-k-l" all_branches initial_ref_map)
  read -r sync_branch sync_old_hash sync_new_hash <<<"$sync_point"

  assert_equal "$sync_branch" "test-chain-d-e-f"
  assert_equal "$sync_old_hash" "${initial_ref_map[test-chain-d-e-f]}"
  assert_equal "$sync_new_hash" "$(git rev-parse test-chain-d-e-f)"
}
