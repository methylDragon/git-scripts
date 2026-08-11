Output media-gen/media/rebase_prefix.gif

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
  Type "tmux kill-session -t git_rebase_prefix_demo 2>/dev/null || true" Enter
  Type "rm -rf /tmp/vhs-repo-rebase-prefix" Enter
  Type "pixi run -q python media-gen/setup_demo_repo.py > /dev/null" Enter
  Type "export GIT_CONFIG_GLOBAL=/dev/null" Enter
  Type "export GIT_CONFIG_SYSTEM=/dev/null" Enter
  Type "export PATH=/tmp/vhs-repo-rebase-prefix:$PATH" Enter
  Type "tmux new-session -s git_rebase_prefix_demo -d" Enter
  Type "tmux set -t git_rebase_prefix_demo status on" Enter
  Type "tmux set -t git_rebase_prefix_demo status-style 'bg=default,fg=white'" Enter
  Type 'tmux set -t git_rebase_prefix_demo status-left ""' Enter
  Type 'tmux set -t git_rebase_prefix_demo window-status-current-format ""' Enter
  Type 'tmux set -t git_rebase_prefix_demo window-status-format ""' Enter
  Type 'tmux set -t git_rebase_prefix_demo status-right "demo: git rebase-prefix "' Enter
  Type "tmux set -t git_rebase_prefix_demo pane-border-style 'fg=colour239'" Enter
  Type "tmux set -t git_rebase_prefix_demo pane-active-border-style 'fg=#ffcc66'" Enter
  Type "tmux split-window -t git_rebase_prefix_demo -v -p 85" Enter
  Type "tmux select-pane -t git_rebase_prefix_demo:0.1" Enter
  Type "tmux split-window -t git_rebase_prefix_demo -h -p 50" Enter
  Type "tmux attach-session -t git_rebase_prefix_demo" Enter
  Ctrl+L

  # Setup Left Pane (Graph)
  Ctrl+B
  Sleep 500ms
  Left
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-rebase-prefix" Enter
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
  
  Type "clear; pixi run -q python media-gen/vhs_utils.py banner 'git rebase-prefix' --subtext 'Rebases all stacks matching prefix onto target. Preserves topology; skips commits already squashed upstream.'; pixi run -q python media-gen/vhs_utils.py comment_reader" Enter

  # Setup Bottom Right Pane (Commands)
  Ctrl+B
  Sleep 500ms
  Down
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-rebase-prefix" Enter
  Type 'export PS1="> "' Enter
  Ctrl+L

  # Initial State Exploration
  Ctrl+B
  Sleep 500ms
  Up
Show

Sleep 6s

Ctrl+L
Type "Notice the branch topology on the left:" Enter
Type "  - @demo/*@ branches are behind (on @main-base@ instead of @main-update@)." Enter
Type "  - @demo/d@ is a shared base of two forking stacks, and @demo/a@ is out of date." Enter
Sleep 6s

# Run the command
Ctrl+L
Type "It would normally be very tedious to manually rebase each stack one by one," Enter
Type "but we can use @git rebase-prefix@ to rebase all stacks matching the @demo/@ prefix at once!" Enter
Enter
Type "*Not shown: rebase conflicts will gracefully pause, giving you the option to resolve them or safely abort the affected stack!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Type "git rebase-prefix demo/"
Sleep 4s
Enter

# Wait for Rebase to Finish
Sleep 4s

# Rebase Explanation Comment
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "Notice how the @demo/*@ branches (e.g., @demo/d@, @demo/d-e-f@, etc.) were seamlessly rebased up to @main-update@!" Enter
Type "Forking stacks and co-located branches were successfully synced up as well." Enter
Sleep 6s

# Explain Delete Merged Branches Prompt
Ctrl+L
Type "@demo/a@ was cherry-picked onto main upstream, so its commits are obsolete!" Enter
Type "@git-scripts@ detects this, and prompts us to cleanly prune the obsolete branch!" Enter
Type "We'll answer the prompt and select 'Delete all'!" Enter
Sleep 2s

# Answer Delete Merged Branches Prompt
Ctrl+B
Sleep 500ms
Down
Type "j" Sleep 500ms Type "j"
Sleep 4s
Enter
Sleep 1s

# Explain Delete effect
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "We deleted the obsolete branches!" Enter
Sleep 4s

# Explain Push Prompt Comment
Ctrl+L
Type "Finally, we are given the option to push the branches we just rebased." Enter
Enter
Type "Since it detects rebased branches, it smartly defaults to @Push All@!" Enter
Type "We'll just hit Enter to confirm." Enter
Sleep 2s

# Switch to command pane to execute push
Ctrl+B
Sleep 500ms
Down
Sleep 4s
Enter
Sleep 4s

# Show result
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "Hooray! All branches rebased, preserving identical topology on the new main!" Enter
Type "Obsolete branch @demo/a@ was safely pruned!" Enter
Sleep 6s

# Cleanup
Sleep 3s
Hide
  Type "tmux capture-pane -p -t git_rebase_prefix_demo:0.2 > /tmp/vhs-out.txt" Enter
  Sleep 1s
  Type "cd /tmp" Enter
  Type "rm -rf /tmp/vhs-repo-rebase-prefix" Enter
Show

