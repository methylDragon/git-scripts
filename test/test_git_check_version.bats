#!/usr/bin/env bash

load "helpers/init.bash"

@test "_git_check_version: fails on old git version" {
  git() {
    if [[ $1 == "--version" ]]; then
      echo "git version 2.37.0"
    else
      # Prevent original git from being called
      return 0
    fi
  }
  export -f git

  run _git_check_version
  assert_failure
  assert_output --partial "Git 2.38+ required"
}

@test "_git_check_version: succeeds on new git version" {
  git() {
    if [[ $1 == "--version" ]]; then
      echo "git version 2.38.0"
    else
      # Prevent original git from being called
      return 0
    fi
  }
  export -f git

  run _git_check_version
  assert_success
}

@test "_git_check_version: succeeds on very new git version" {
  git() {
    if [[ $1 == "--version" ]]; then
      echo "git version 3.0.0"
    else
      # Prevent original git from being called
      return 0
    fi
  }
  export -f git

  run _git_check_version
  assert_success
}
