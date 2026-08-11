Output media-gen/media/gh_align_pr_bases_and_sync_stacks.gif

Require git

Set CursorBlink true
Set FontSize 18
Set Width 1500
Set Height 750
Set Padding 40
Set Theme "GruvboxDarkHard"
Set WindowBar Colorful
Set TypingSpeed 10ms

# Setup
Hide
  Type "tmux kill-session -t git_gh_align_pr_bases_and_sync_stacks_demo 2>/dev/null || true" Enter
  Type "rm -rf /tmp/vhs-repo-gh-align" Enter
  Type "pixi run -q python media-gen/setup_demo_repo.py --scenario gh-align > /dev/null" Enter
  Type "export GIT_CONFIG_GLOBAL=/dev/null" Enter
  Type "export GIT_CONFIG_SYSTEM=/dev/null" Enter
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "tmux new-session -s git_gh_align_pr_bases_and_sync_stacks_demo -d" Enter
  Type "tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo status on" Enter
  Type "tmux set -g status-right-length 100" Enter
  Type "tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo status-style 'bg=default,fg=white'" Enter
  Type 'tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo status-left ""' Enter
  Type 'tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo window-status-current-format ""' Enter
  Type 'tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo window-status-format ""' Enter
  Type 'tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo status-right "demo: git gh-align-pr-bases-and-sync-stacks "' Enter
  Type "tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo pane-border-style 'fg=colour239'" Enter
  Type "tmux set -t git_gh_align_pr_bases_and_sync_stacks_demo pane-active-border-style 'fg=#ffcc66'" Enter
  Type "tmux split-window -t git_gh_align_pr_bases_and_sync_stacks_demo -v -p 85" Enter
  Type "tmux select-pane -t git_gh_align_pr_bases_and_sync_stacks_demo:0.1" Enter
  Type "tmux split-window -t git_gh_align_pr_bases_and_sync_stacks_demo -h -p 50" Enter
  Type "tmux attach-session -t git_gh_align_pr_bases_and_sync_stacks_demo" Enter
  Ctrl+L

  # Setup Left Pane (Graph)
  Ctrl+B
  Sleep 500ms
  Left
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-gh-align" Enter
  Type 'export PS1="> "' Enter
  Ctrl+L
  Type "watch -c -t -n 1 'git log --graph --oneline --all --decorate --color'" Enter
  Sleep 500ms

  # Setup Top Right Pane (Comments)
  Ctrl+B
  Sleep 500ms
  Right
  Ctrl+B
  Sleep 500ms
  Up
  Sleep 500ms
  Type 'export PS1=""' Enter
  
  Type "clear; pixi run -q python media-gen/vhs_utils.py banner 'git gh-align-pr-bases-and-sync-stacks' --subtext 'Aligns PR bases and syncs local stacks.'; pixi run -q python media-gen/vhs_utils.py comment_reader" Enter

  # Setup Bottom Right Pane (Commands)
  Ctrl+B
  Sleep 500ms
  Down
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "export GIT_SCRIPTS_DEMO=1" Enter
  Type "cd /tmp/vhs-repo-gh-align" Enter
  Type 'export PS1="> "' Enter
  Ctrl+L

  # Initial State Exploration
  Ctrl+B
  Sleep 500ms
  Up
Show

Sleep 4s

Ctrl+L
Type "Notice the branch topology on the left:" Enter
Type "  - We have a stack of branches: base -> mid -> tip." Enter
Type "  - When using Stacked PRs on GitHub, each PR's 'base' should point to the branch immediately below it, not main." Enter
Sleep 6s

# Run the command
Ctrl+L
Type "Manually aligning GitHub PRs to match local topology is tedious and error-prone." Enter
Type "Let's use @git gh-align-pr-bases-and-sync-stacks@ to do it automatically via the GitHub API!" Enter
Enter
Type "It will also detect and let us create PRs for branches that don't have them." Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Type "git gh-align-pr-bases-and-sync-stacks"
Sleep 4s
Enter

# Wait for PR Creation prompt
Sleep 3s

# Explain PR creation selection
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "The tool detected branches missing PRs. Notice we can choose which ones to create PRs for." Enter
Enter
Type "Suppose we only want to send PRs up to @demo/d-e-f@ (e.g., because we're still developing downstream branches)," Enter
Type "we can only select @demo/d-e-f@ by pressing Space, then Enter." Enter
Enter
Sleep 2s

# Answer PR Creation prompt
Ctrl+B
Sleep 500ms
Down
Type " "
Sleep 4s
Enter
Sleep 2s

# Wait for alignment prompt
Sleep 2s

# Explain prompt
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "The tool identified the branches that need to be synced, and prepared a draft PR for our missing branch (@demo/d-e-f@)!" Enter
Type "We'll confirm applying the PR base changes by typing 'y' and hitting Enter." Enter
Sleep 2s

# Answer alignment prompt
Ctrl+B
Sleep 500ms
Down
Type "y"
Sleep 4s
Enter

# Wait for edits and creates to finish (takes ~2s) and stack sync prompt to appear
Sleep 4s

# Explain stack sync prompt
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "Since we have multiple branches, it asks if we want to synchronize our GitHub stack using the @gh stack@ extension." Enter
Type "We'll confirm this by typing 'y' and hitting Enter." Enter
Sleep 2s

# Answer stack sync prompt
Ctrl+B
Sleep 500ms
Down
Type "y"
Sleep 4s
Enter

# Wait for stack sync to finish
Sleep 6s

# Explain result
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "Hooray! The tool used the GitHub API to seamlessly create missing PRs, align all PR bases, and sync our GitHub stack!" Enter
Type "Our local topology is perfectly mirrored on the remote." Enter
Sleep 6s

# Cleanup
Sleep 3s
Hide
  Type "tmux capture-pane -p -t git_gh_align_pr_bases_and_sync_stacks_demo:0.2 > /tmp/vhs-out.txt" Enter
  Sleep 1s
  Type "cd /tmp" Enter
  Type "rm -rf /tmp/vhs-repo-gh-align" Enter
Show

