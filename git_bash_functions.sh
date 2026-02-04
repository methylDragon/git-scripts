# ==============================================================================
# GIT STACK UTILITIES
#
# High-performance tools for managing "stacked diffs".
#
# OPTIMIZATIONS (Verified Safe):
#   - Uses `git merge-base --independent` for O(1) tip detection.
#   - Uses `git rebase <upstream> <branch>` to skip redundant checkouts.
#   - Uses `git branch --merged` for fast summary generation.
#
# Dependencies: git >= 2.38 (requires --update-refs)
# ==============================================================================

# ------------------------------------------------------------------------------
# PRIVATE HELPERS
# ------------------------------------------------------------------------------

_git_check_version() {
  local v
  v=$(git --version | awk '{print $3}')
  if [[ "$(printf '%s\n' "2.38" "$v" | sort -V | head -n1)" != "2.38" ]]; then
    echo "❌ Error: Git 2.38+ required (detected $v)."
    return 1
  fi
}

_git_is_ancestor() {
  git merge-base --is-ancestor "$1" "$2"
}

# Checks if a branch is content-equivalent to upstream.
# 1. Checks for Patch-ID matches (standard rebase/merge detection).
# 2. Checks for Tree-ID equality (squash merge detection).
_git_is_obsolete() {
  local commit="$1"
  local target="$2"

  # Strategy 1: Patch-ID Match (Fast)
  # If git cherry finds no "+" (meaning all commits have an equivalent in target),
  # the branch is obsolete.
  if ! git cherry "$target" "$commit" | grep -q "^+"; then
    return 0
  fi

  # Strategy 2: Content Result Match (Robust for Squash Merges)
  # If Strategy 1 failed, it might be a squash merge.
  # We simulate a merge of the commit into the target. If the resulting tree
  # is EXACTLY the same as the target's current tree, then the branch
  # introduces no new changes (it was already squashed in).
  local target_tree
  target_tree=$(git rev-parse "$target^{tree}")

  local merge_tree
  # 'git merge-tree --write-tree' (Git 2.38+) performs a server-side merge.
  # We suppress stderr; if it conflicts, the tree won't match anyway.
  merge_tree=$(git merge-tree --write-tree "$target" "$commit" 2>/dev/null)

  if [[ "$merge_tree" == "$target_tree" ]]; then
    return 0
  fi

  # Strategy 3: Tree Hash Match in History (Handles Reverts)
  # This is a fallback for complex cases like reverts or certain types of
  # squash merges where the above checks aren't sufficient.
  # We check if the exact tree of the commit exists anywhere in the target's
  # recent history.
  local commit_tree
  commit_tree=$(git rev-parse "$commit^{tree}")
  local target_history_trees
  target_history_trees=$(git log --max-count=100 --pretty=%T "$target")
  if echo "$target_history_trees" | grep -Fxq "$commit_tree"; then
    return 0
  fi

  return 1
}

# Safe update of the target branch.
#
# Checks if branch exists -> Checks if upstream exists -> Pulls or Warns.
_git_update_target() {
  local target="$1"

  if ! git show-ref --verify --quiet "refs/heads/$target"; then
    echo "❌ Error: Target branch '$target' does not exist locally."
    return 1
  fi

  # Switch to target (if not already there)
  local current
  current=$(git branch --show-current)
  if [[ "$current" != "$target" ]]; then
    if ! git checkout "$target" 2>/dev/null; then
      echo "❌ Error: Could not checkout '$target'."
      return 1
    fi
  fi

  # Check if upstream exists
  local upstream
  upstream=$(git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>/dev/null)

  if [[ -n "$upstream" ]]; then
    echo "🔄 Pulling updates from $upstream..."
    if ! git pull --rebase; then
      echo "❌ Error: Could not pull updates. Aborting."
      return 1
    fi
  else
    echo "⚠️  '$target' is local-only (no upstream). Using current state."
  fi
}

# Optimized Tip Detection.
#
# Uses `git merge-base --independent` to filter the list in O(1) Git operations.
_git_find_tips() {
  local branches=("${@}")
  local tips=()

  for branch in "${branches[@]}"; do
    local is_tip=true
    for other_branch in "${branches[@]}"; do
      if [[ "$branch" != "$other_branch" ]] && git merge-base --is-ancestor "$branch" "$other_branch"; then
        is_tip=false
        break
      fi
    done
    if [[ "$is_tip" == "true" ]]; then
      tips+=("$branch")
    fi
  done

  printf "%s\n" "${tips[@]}" | sort -u
}

# Find the optimal "Cut Point" commit for the purposes of rebasing.
#
# Walks backwards from the Tip. The first ancestor we encounter that is
# "obsolete" (in target) is our cut point.
_git_find_cut_point() {
  local tip="$1"
  local target="$2"

  # Get list of commits in Tip that are NOT in Target (linearized)
  # We limit the lookback to prevent scanning the entire history of the repo if divergent.
  local commits
  commits=$(git rev-list --max-count=100 "$target..$tip")

  for commit in $commits; do
    # We are walking backwards (Newest -> Oldest).
    #
    # The MOMENT we hit a commit that IS obsolete/merged, that is our cut point.
    # Everything after it is unique work.
    if _git_is_obsolete "$commit" "$target"; then
      echo "$commit"
      return 0
    fi
  done
}

# Finds the best sync point for a branch that is part of a forking stack.
#
# When rebasing forking stacks, we need to be careful to not rebase the
# shared history twice. This function finds the closest ancestor of the
# given branch that has already been rebased, and returns the branch name,
# the old hash, and the new hash of that ancestor.
#
# Args:
#   1: The branch to find the sync point for.
#   2: The list of all branches in the stack.
#   3: The map of initial branch hashes.
#
# Output:
#   A string containing the sync branch, the old hash, and the new hash,
#   separated by spaces.
_git_find_sync_point() {
  local branch="$1"
  declare -n _all_branches="$2"
  declare -n _initial_ref_map="$3"

  echo "branch: $branch" >&2
  echo "_all_branches: ${_all_branches[@]}" >&2
  echo "_initial_ref_map: " >&2
  for key in "${!_initial_ref_map[@]}"; do
    echo "  $key: ${_initial_ref_map[$key]}" >&2
  done


  local sync_branch=""
  local sync_old_hash=""
  local sync_new_hash=""
  local best_dist=999999

  for candidate in "${_all_branches[@]}"; do
    [[ "$candidate" == "$branch" ]] && continue

    # 1. Check Ancestry using SNAPSHOT hashes.
    # We must use the old topology to establish relationship, as the candidate
    # might have already moved to the new topology.
    local candidate_initial_hash="${_initial_ref_map[$candidate]}"
    echo "checking ancestor: $candidate_initial_hash $branch" >&2
    if git merge-base --is-ancestor "$candidate_initial_hash" "$branch"; then
      # 2. Check for Movement.
      # Has this ancestor been rebased by a previous iteration of this loop?
      local candidate_curr_hash
      candidate_curr_hash=$(git rev-parse "$candidate")
      if [[ "$candidate_curr_hash" != "$candidate_initial_hash" ]]; then
        # 3. Calculate Distance using INITIAL hashes.
        # We must measure "how close" the ancestor is on the ORIGINAL graph.
        local dist
        dist=$(git rev-list --count "$candidate_initial_hash..$branch")
        if ((dist < best_dist)); then
          best_dist=$dist
          sync_branch="$candidate"
          sync_old_hash="$candidate_initial_hash"
          sync_new_hash="$candidate_curr_hash"
        fi
      fi
    fi
  done

  echo "$sync_branch $sync_old_hash $sync_new_hash"
}

# Generates a visual tree string for the stack.
# Format:
#   TipBranch
#     ├─ ChildBranch
#     └─ ChildBranch
#
# Args:
#   1: Tip Branch
#   2: Prefix (Optional filter)
#   3: Target (Optional filter)
#   4: FilterMerged (true/false)
#   5: AllowedRefs (Optional: Space-separated whitelist of branches to include)
_git_format_stack_tree() {
  local tip="$1"
  local prefix="$2"
  local target="$3"
  local filter_merged_in_target="$4" # "true" or "false"
  local allowed_refs="$5"             # Space-separated list of allowed branches

  local tree="$tip"
  local stack_refs

  # Optimization: Use prefix in git command if available
  if [[ -n "$prefix" ]]; then
    stack_refs=$(git branch --format='%(refname:short)' --list "${prefix}*" --merged "$tip")
  else
    stack_refs=$(git branch --format='%(refname:short)' --merged "$tip")
  fi

  local target_refs=""
  if [[ "$filter_merged_in_target" == "true" ]] && [[ -n "$target" ]]; then
    target_refs=$(git branch --format='%(refname:short)' --list "${prefix}*" --merged "$target")
  fi

  # Accumulate children
  local children=()
  for ref in $stack_refs; do
    [[ "$ref" == "$tip" ]] && continue

    # Filter: Allowed Refs (Whitelist)
    if [[ -n "$allowed_refs" ]]; then
      if [[ ! " $allowed_refs " =~ " $ref " ]]; then continue; fi
    fi

    # Filter: Already merged in target
    if [[ "$filter_merged_in_target" == "true" ]] && [[ "$target_refs" == *"$ref"* ]]; then
      continue
    fi
    children+=("$ref")
  done

  # Sort children by distance from the tip so that the tree is displayed
  # in a more logical order (closest to the tip first).
  if [ ${#children[@]} -gt 0 ]; then
    local sorted_children=()
    for child in "${children[@]}"; do
      local distance
      distance=$(git rev-list --count "$child..$tip")
      sorted_children+=("$distance $child")
    done

    IFS=$'\n' sorted_children=($(sort -n <<<"${sorted_children[*]}"))
    unset IFS

    children=()
    for item in "${sorted_children[@]}"; do
      children+=("${item#* }")
    done
  fi

  # Format the tree
  local count=${#children[@]}
  for ((i = 0; i < count; i++)); do
    local child="${children[$i]}"

    # Check if this is the last child in the list
    if ((i == count - 1)); then
      tree+=$'\n    └─ '"$child"
    else
      tree+=$'\n    ├─ '"$child"
    fi
  done

  echo "$tree"
}

# ------------------------------------------------------------------------------
# PUBLIC FUNCTIONS
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# git_rebase_prefix <prefix> [target_branch]
#
# Batch updates stacks. Handles squash-merged upstreams automatically.
# For any branches found to already be included in upstream, prompts to optionally delete
# their local branches.
#
# This function identifies "tip" branches (branches that are not ancestors of any other
# matching branch) and rebases them using `git rebase --update-refs`.
#
# Key Features:
#   - Preserves Topology: If you have a stack A -> B -> C, rebasing C will automatically
#     update A and B to the correct new commits, keeping the stack intact.
#   - Atomic Failure: If a conflict occurs anywhere in the stack (e.g., in A), the rebase
#     for the entire stack (A, B, and C) is aborted and reverted to the original state.
#   - Summary: Records successes and failures per stack and prints a summary at the end.
#
# Usage:
#   rebase_prefix <prefix> [target_branch]
#   rebase_prefix -h | --help
# ------------------------------------------------------------------------------
git_rebase_prefix() {
  _git_check_version || return 1

  local prefix="$1"
  local target="${2:-main}"
  local start_branch
  start_branch=$(git rev-parse --abbrev-ref HEAD)

  [[ -z "$prefix" ]] && { echo "❌ Error: Missing <prefix>."; return 1; }

  if ! _git_update_target "$target"; then
    git checkout "$start_branch" 2>/dev/null
    return 1
  fi

  echo "🔍 Scanning 'refs/heads/${prefix}*'..."
  local all_branches=($(git for-each-ref --format='%(refname:short)' "refs/heads/${prefix}*"))
  all_branches=(${all_branches[@]/$target})

  if [[ ${#all_branches[@]} -eq 0 ]]; then
    echo "  No matching branches found."
    git checkout "$start_branch" 2>/dev/null
    return 0
  fi

  local unique_tips=($(_git_find_tips "${all_branches[@]}"))
  echo "  Found ${#unique_tips[@]} stack tips."

  # Snapshotting
  # We must map every branch to its hash BEFORE we start rebasing anything.
  # This allows us to calculate topological distance on the "Original Graph"
  # later, even after we have started moving parts of the tree.
  declare -A initial_ref_map
  for branch in "${all_branches[@]}"; do
    initial_ref_map["$branch"]=$(git rev-parse "$branch")
  done

  local success_log=()
  local skipped_log=()
  local failed_log=()
  local skipped_branches_flat=()
  local kept_branches_flat=()

  for branch in "${unique_tips[@]}"; do
    echo -e "\n----------------------------------------"
    echo "### Processing Stack: $branch ###"

    # Identify all branches in this current stack
    local stack_refs
    stack_refs=$(git branch --format='%(refname:short)' --list "${prefix}*" --merged "$branch")

    # --- Case 1: Skipped (Fully Merged) ---
    if _git_is_obsolete "$branch" "$target"; then
      echo "💤 Fully merged. Skipping."
      # For skipped stacks, we show ALL branches in the stack (so user knows what to delete)
      skipped_log+=("$(_git_format_stack_tree "$branch" "$prefix" "$target" "false")")

      # Collect these branches as candidates for deletion
      for ref in $stack_refs; do
        skipped_branches_flat+=("$ref")
      done
      continue
    fi

    # If not skipped, we are attempting to keep these branches (either updated or failed)
    for ref in $stack_refs; do
      kept_branches_flat+=("$ref")
    done

    # --- Case 2: Rebase ---
    # If a stack forks, and we rebase one of the forks, the common history
    # is duplicated. To avoid this, we need to find the closest ancestor
    # of the current branch that has already been rebased, and then rebase
    # the current branch on top of that.
    local sync_point
    sync_point=$(_git_find_sync_point "$branch" all_branches initial_ref_map)
    read -r sync_branch sync_old_hash sync_new_hash <<<"$sync_point"

    local rebase_ok=false
    if [[ -n "$sync_branch" ]]; then
      echo "    ✨ Detected shared history! Linking onto updated '$sync_branch'..."
      if git rebase --update-refs --onto "$sync_new_hash" "$sync_old_hash" "$branch"; then
        rebase_ok=true
      fi
    else
      local cut_point
      cut_point=$(_git_find_cut_point "$branch" "$target")
      if [[ -n "$cut_point" ]]; then
        echo "⚡ Found obsolete ancestor: ${cut_point:0:7}"
        echo "  Dropping it; grafting stack onto $target..."
        if git rebase --update-refs --onto "$target" "$cut_point" "$branch"; then
          rebase_ok=true
        fi
      else
        echo "  Standard rebase onto $target..."
        if git rebase --update-refs "$target" "$branch"; then
          rebase_ok=true
        fi
      fi
    fi

    # --- Case 3: Result Logging ---
    if [[ "$rebase_ok" == true ]]; then
      # For updated stacks, we hide branches that are ALREADY in target (redundant info)
      success_log+=("$(_git_format_stack_tree "$branch" "$prefix" "$target" "true")")
    else
      echo "❌ Conflict. Aborting."
      git rebase --abort 2>/dev/null
      # For failed stacks, show full context
      failed_log+=("$(_git_format_stack_tree "$branch" "$prefix" "$target" "false")")
    fi
  done

  # Summary Output
  echo -e "\n========================================"
  echo "BATCH SUMMARY"
  echo "========================================"

  if [[ ${#success_log[@]} -gt 0 ]]; then
    printf "✅ Updated Stacks:\n"
    for entry in "${success_log[@]}"; do
      echo " - $entry"
    done | sed 's/^/    /' # Indent for cleaner look
  fi

  if [[ ${#skipped_log[@]} -gt 0 ]]; then
    printf "\n💤 Skipped (Fully Merged):\n"
    for entry in "${skipped_log[@]}"; do
      echo " - $entry"
    done | sed 's/^/    /'
  fi

  if [[ ${#failed_log[@]} -gt 0 ]]; then
    printf "\n⚠️  Failed (Manual Fix Needed):\n"
    for entry in "${failed_log[@]}"; do
      echo " - $entry"
    done | sed 's/^/    /'
  fi

  # --- Cleanup Prompt ---
  if [[ ${#skipped_branches_flat[@]} -gt 0 ]]; then
    local branches_to_delete=()
    local kept_str=" ${kept_branches_flat[*]} "

    # Only delete branches that are NOT also part of a kept/failed stack
    # (This handles shared base branches correctly)
    for cand in "${skipped_branches_flat[@]}"; do
      if [[ "$kept_str" != *" $cand "* ]]; then
        branches_to_delete+=("$cand")
      fi
    done

    if [[ ${#branches_to_delete[@]} -gt 0 ]]; then
      # Deduplicate list
      local unique_to_delete=($(printf "%s\n" "${branches_to_delete[@]}" | sort -u))

      echo ""
      echo -n "❓ Delete the ${#unique_to_delete[@]} fully merged local branch(es)? [y/N] "
      read -r reply
      if [[ "$reply" =~ ^[Yy]$ ]]; then
        echo "🔥 Deleting branches..."
        # Use -D to force delete since we already confirmed they are obsolete/merged via script logic
        git branch -D "${unique_to_delete[@]}"
      fi
    fi
  fi

  git checkout "$start_branch" 2>/dev/null
  [[ ${#failed_log[@]} -gt 0 ]] && return 1 || return 0
}

# ------------------------------------------------------------------------------
# git_evolve
#
# Usage:
#   git_evolve
#   git_evolve <old_base_commit_sha>
#
# Rescues orphaned children after a parent amend/rebase.
# Automatically detects displaced stacks and rebases them with --update-refs.
# ------------------------------------------------------------------------------
git_evolve() {
  _git_check_version || return 1

  local new_hash old_hash current_branch reply
  local orphans=()

  # Snapshotting
  #
  # We must map every branch to its hash BEFORE we start rebasing anything.
  #
  # This allows us to calculate topological distance on the "Original Graph"
  # later, even after we have started moving parts of the tree.
  declare -A initial_ref_map

  new_hash=$(git rev-parse HEAD)
  current_branch=$(git branch --show-current)

  if [ -n "$1" ]; then
    old_hash=$(git rev-parse --verify "$1")
  else
    if ! old_hash=$(git rev-parse --verify HEAD@{1} 2>/dev/null); then
      echo "❌ Error: Could not find previous HEAD in reflog."
      echo "Usage: git_evolve <OLD_HASH>"
      return 1
    fi
    echo "ℹ️  No hash provided. Auto-detected previous HEAD: ${old_hash:0:7}"
  fi

  if [ "$old_hash" == "$new_hash" ]; then
    echo "✅ HEAD is identical to the target hash. Nothing to evolve."
    return 0
  fi

  echo "🔍 Scanning for stacks displaced by move from ${old_hash:0:7} to ${new_hash:0:7}..."

  # Find branches currently pointing to the OLD history
  local candidates
  candidates=$(git branch --format='%(refname:short)' --contains "$old_hash")

  for branch in $candidates; do
    [[ "$branch" == "$current_branch" ]] && continue
    if _git_is_ancestor "$new_hash" "$branch"; then continue; fi

    orphans+=("$branch")
    initial_ref_map["$branch"]=$(git rev-parse "$branch")
  done

  if [ ${#orphans[@]} -eq 0 ]; then
    echo "✅ No displaced branches found."
    return 0
  fi

  # Filter for Tips only (let --update-refs handle the bodies)
  local unique_tips=($(_git_find_tips "${orphans[@]}"))

  echo "⚡ Found ${#unique_tips[@]} stack tip(s) (covering ${#orphans[@]} branches):"
  for tip in "${unique_tips[@]}"; do
    local tree_view
    tree_view=$(_git_format_stack_tree "$tip" "" "" "false" "${orphans[*]}")
    echo "$tree_view" | sed '1s/^/    - /; 2,$s/^/        /'
  done
  echo ""

  echo -n "❓ Rebase these stacks onto ${new_hash:0:7} using --update-refs? (y/n) "
  read -r reply
  echo ""

  local failed_log=()
  local success_count=0

  if [[ "$reply" =~ ^[Yy]$ ]]; then
    for tip in "${unique_tips[@]}"; do
      echo "🔗 Reconnecting stack '$tip'..."

      # Dynamic Topology Linking
      #
      # If Stack A and B share a base (e.g., 'feature-x'), and we rebase Stack A first,
      # 'feature-x' moves to a new hash. When we process Stack B, we must detect this movement
      # and graft Stack B onto the NEW 'feature-x' to avoid duplicating commits.

      local sync_branch=""
      local sync_old_hash=""
      local sync_new_hash=""
      local best_dist=999999

      for candidate in "${orphans[@]}"; do
        [[ "$candidate" == "$tip" ]] && continue

        # 1. Check Ancestry using SNAPSHOT hashes.
        # We must use the old topology to establish relationship, as the candidate
        # might have already moved to the new topology.
        local candidate_initial_hash="${initial_ref_map[$candidate]}"

        if _git_is_ancestor "$candidate_initial_hash" "$tip"; then

          # 2. Check for Movement.
          # Has this ancestor been rebased by a previous iteration of this loop?
          local candidate_curr_hash
          candidate_curr_hash=$(git rev-parse "$candidate")

          if [[ "$candidate_curr_hash" != "$candidate_initial_hash" ]]; then
            # 3. Calculate Distance using INITIAL hashes.
            # We must measure "how close" the ancestor is on the ORIGINAL graph.
            # Comparing Old-Hash vs New-Hash yields invalid distances.
            local dist
            dist=$(git rev-list --count "$candidate_initial_hash..$tip")

            if ((dist < best_dist)); then
              best_dist=$dist
              sync_branch="$candidate"
              sync_old_hash="$candidate_initial_hash"
              sync_new_hash="$candidate_curr_hash"
            fi
          fi
        fi
      done

      # Execute Rebase
      if [[ -n "$sync_branch" ]]; then
        echo "    ✨ Detected shared history! Linking onto updated '$sync_branch'..."
        # Rebase Range: (Old_Sync_Hash .. Tip] -> Onto New_Sync_Hash
        if git rebase --update-refs --onto "$sync_new_hash" "$sync_old_hash" "$tip"; then
          echo "    ✅ Success."
          ((++success_count))
        else
          echo "    💥 Conflict. Aborting..."
          git rebase --abort 2>/dev/null
          failed_log+=("$(_git_format_stack_tree "$tip" "" "" "false" "${orphans[*]}")")
        fi
      else
        # Standard Rebase: (Old_Base .. Tip] -> Onto New_Base
        if git rebase --update-refs --onto "$new_hash" "$old_hash" "$tip"; then
          echo "    ✅ Success."
          ((++success_count))
        else
          echo "    💥 Conflict. Aborting..."
          git rebase --abort 2>/dev/null
          failed_log+=("$(_git_format_stack_tree "$tip" "" "" "false" "${orphans[*]}")")
        fi
      fi
    done

    echo -e "\n========================================"
    if [[ ${#failed_log[@]} -eq 0 ]]; then
      echo "✨ All Done! ($success_count stacks evolved)"
      git checkout "$current_branch" 2>/dev/null
      return 0
    else
      echo "⚠️  SUMMARY: $success_count succeeded, ${#failed_log[@]} failed."
      echo "    The repository has been reset to clean state (per stack)."
      echo "    The following stacks require manual intervention:"
      for entry in "${failed_log[@]}"; do
        echo "  - $entry"
      done | sed 's/^/  /'
      git checkout "$current_branch" 2>/dev/null
      return 1
    fi
  else
    echo "❌ Operation cancelled."
  fi
}

# ------------------------------------------------------------------------------
# git_push_prefix <prefix> [options]
#
# Usage:
#   git_push_prefix "feature/login-"
#   git_push_prefix "feature/login-" --force-with-lease
#
# Atomically pushes branches matching the prefix to origin.
# Skips branches where local HEAD == origin HEAD.
# ------------------------------------------------------------------------------
git_push_prefix() {
  local prefix="$1"
  shift
  local push_opts=("$@")

  [[ -z "$prefix" ]] && { echo "❌ Error: Missing <prefix>."; return 1; }

  echo "🔄 Fetching origin..."
  git fetch origin

  echo "🔍 Scanning 'refs/heads/${prefix}*'..."

  local branches_to_push=()
  local up_to_date_count=0

  # Iterate over local branches with their hash
  # Format: branch_name commit_hash
  while read -r branch local_hash; do
    # Resolve the hash of the remote tracking branch (from local cache)
    # We suppress errors because the remote branch might not exist yet (new branch).
    local remote_hash
    remote_hash=$(git rev-parse --verify "refs/remotes/origin/$branch" 2>/dev/null)

    # Push if remote is missing OR if hashes differ
    if [[ -z "$remote_hash" ]]; then
      branches_to_push+=("$branch") # New branch
    elif [[ "$local_hash" != "$remote_hash" ]]; then
      branches_to_push+=("$branch") # Has updates (or needs force push)
    else
      ((++up_to_date_count))
    fi
  done < <(git for-each-ref --format='%(refname:short) %(objectname)' "refs/heads/${prefix}*")

  if [[ ${#branches_to_push[@]} -eq 0 ]]; then
    if [[ $up_to_date_count -eq 0 ]]; then
      echo "    No matching branches found."
    else
      echo "✅ All matched branches ($up_to_date_count) are already up-to-date with origin."
    fi
    return 0
  fi

  echo "📦 Found ${#branches_to_push[@]} branches to push (Skipped $up_to_date_count up-to-date):"
  printf "    - %s\n" "${branches_to_push[@]}"

  echo -e "\n🚀 Pushing to origin (Options: ${push_opts[*]:-(none)})..."

  if git push origin "${branches_to_push[@]}" "${push_opts[@]}"; then
    echo -e "\n✅ Batch push complete."
  else
    echo -e "\n❌ Push failed. Check remote permissions or try --force-with-lease."
    return 1
  fi
}

# ------------------------------------------------------------------------------
# git_prune_local_branches [options]
#
# Usage:
#   git_prune_local_branches
#   git_prune_local_branches --dry-run
#
# Prunes local branches whose tracking branch is gone from the remote.
# ------------------------------------------------------------------------------
git_prune_local_branches() {
  local dry_run=false
  if [[ "$1" == "-n" ]] || [[ "$1" == "--dry-run" ]]; then
    echo "Running git_prune_local_branches in dry-run mode..."
    dry_run=true
  fi

  echo "🔄 Fetching origin --prune..."
  git fetch -p

  # Safe parsing: 'git branch -vv' puts a '*' in column 1 if it's the current branch.
  # We check for that to ensure we get the branch name (column 2) in that case.
  local branches
  branches=$(git branch -vv | grep ': gone]' | awk '{if ($1 == "*") print $2; else print $1}')

  if [[ -z "$branches" ]]; then
    echo "✅ No orphaned branches found."
    return 0
  fi

  if [[ "$dry_run" == "true" ]]; then
    echo "📦 [Dry Run] The following branches would be deleted:"
    echo "$branches" | sed 's/^/    - /'
    return 0
  fi

  echo "🗑️ Pruning branches..."
  echo "$branches" | xargs git branch -D
}

# ------------------------------------------------------------------------------
# git_prune_remote_prefix <prefix> [target_branch] [options]
#
# Examples:
#   git_prune_remote_prefix "feature/old-work-"
#   git_prune_remote_prefix "feature/" main --dry-run
#
# Prunes REMOTE branches matching <prefix> that are fully merged/obsolete
# in the target branch (default: main).
# ------------------------------------------------------------------------------
git_prune_remote_prefix() {
  local prefix="$1"
  shift
  local target="main"
  local dry_run=false

  # Argument parsing
  while [[ $# -gt 0 ]]; do
    case "$1" in
    -n | --dry-run)
      echo "Running git_prune_remote_prefix in dry-run mode..."
      dry_run=true
      ;;
    *) target="$1" ;;
    esac
    shift
  done

  [[ -z "$prefix" ]] && { echo "❌ Error: Missing <prefix>."; return 1; }

  echo "🔄 Fetching origin..."
  git fetch origin

  # Verify remote target exists
  if ! git rev-parse --verify "origin/$target" >/dev/null 2>&1; then
    echo "❌ Error: Remote target 'origin/$target' not found."
    return 1
  fi

  echo "🔍 Scanning 'origin/${prefix}*' for obsolete branches..."

  # Use for-each-ref for safe parsing
  local remote_branches=($(git for-each-ref --format='%(refname:short)' "refs/remotes/origin/${prefix}*"))

  if [[ ${#remote_branches[@]} -eq 0 ]]; then
    echo "    No matching remote branches found."
    return 0
  fi

  local to_delete=()

  for branch in "${remote_branches[@]}"; do
    # Skip the target itself or HEAD
    [[ "$branch" == "origin/HEAD" ]] && continue
    [[ "$branch" == "origin/$target" ]] && continue

    # Reuse the logic: Checks for exact ancestry OR patch-ID match (squash merge)
    if _git_is_obsolete "$branch" "origin/$target"; then
      # Strip 'origin/' prefix for the push command
      local clean_name="${branch#origin/}"
      to_delete+=("$clean_name")
    fi
  done

  if [[ ${#to_delete[@]} -eq 0 ]]; then
    echo "✅ No obsolete remote branches found."
    return 0
  fi

  echo "🗑️  Found ${#to_delete[@]} obsolete remote branches:"
  printf "    - %s\n" "${to_delete[@]}"

  if [[ "$dry_run" == "true" ]]; then
    echo -e "\n📦 [Dry Run] No changes made."
    return 0
  fi

  echo -e "\n🔥 Deleting from origin..."
  # Atomic delete
  if git push origin --delete "${to_delete[@]}"; then
    echo "✅ Remote cleanup complete."
  else
    echo "❌ Error during deletion."
    return 1
  fi
}