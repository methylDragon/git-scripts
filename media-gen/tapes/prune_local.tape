Output media-gen/media/prune_local.gif

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
  Type "tmux kill-session -t git_prune_local_demo 2>/dev/null || true" Enter
  Type "rm -rf /tmp/vhs-repo-prune-local" Enter
  Type "pixi run -q python media-gen/setup_demo_repo.py --scenario prune-local > /dev/null" Enter
  Type "export GIT_CONFIG_GLOBAL=/dev/null" Enter
  Type "export GIT_CONFIG_SYSTEM=/dev/null" Enter
  Type "export PATH=/tmp/vhs-repo-prune-local:$PATH" Enter
  Type "tmux new-session -s git_prune_local_demo -d" Enter
  Type "tmux set -t git_prune_local_demo status on" Enter
  Type "tmux set -t git_prune_local_demo status-style 'bg=default,fg=white'" Enter
  Type 'tmux set -t git_prune_local_demo status-left ""' Enter
  Type 'tmux set -t git_prune_local_demo window-status-current-format ""' Enter
  Type 'tmux set -t git_prune_local_demo window-status-format ""' Enter
  Type 'tmux set -t git_prune_local_demo status-right "demo: git prune-local "' Enter
  Type "tmux set -t git_prune_local_demo pane-border-style 'fg=colour239'" Enter
  Type "tmux set -t git_prune_local_demo pane-active-border-style 'fg=#ffcc66'" Enter
  Type "tmux split-window -t git_prune_local_demo -v -p 85" Enter
  Type "tmux select-pane -t git_prune_local_demo:0.1" Enter
  Type "tmux split-window -t git_prune_local_demo -h -p 50" Enter
  Type "tmux attach-session -t git_prune_local_demo" Enter
  Ctrl+L

  # Setup Left Pane (Graph)
  Ctrl+B
  Sleep 500ms
  Left
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-prune-local" Enter
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
  
  Type "clear; pixi run -q python media-gen/vhs_utils.py banner 'git prune-local' --subtext 'Prunes local branches after an obsolescence check (fetch --prune).'; pixi run -q python media-gen/vhs_utils.py comment_reader" Enter

  # Setup Bottom Right Pane (Commands)
  Ctrl+B
  Sleep 500ms
  Down
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-prune-local" Enter
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
Type "  - We have a messy @local@ history." Enter
Type "  - Behind the scenes, some of our remote branches have been deleted (e.g., from merging Pull Requests)." Enter
Sleep 6s

# Run the command
Ctrl+L
Type "Git leaves our local tracking branches hanging around, making things messy." Enter
Type "Let's use @git prune-local@ to perform an obsolescence check and safely clean up!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Type "git prune-local"
Sleep 4s
Enter

# Wait for Prompt
Sleep 2s

# Explain prompt
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "The tool instantly identifies any local branch whose remote tracking branch no longer exists! (e.g., @demo/a-b-c@, @demo/d-e@, @demo/d-e-f-j-k@)" Enter
Type "It provides an interactive prompt so we can safely review and select which ones to delete." Enter
Type "We'll answer the prompt and select 'Delete all'!" Enter
Sleep 2s

# Answer prompt
Ctrl+B
Sleep 500ms
Down
Type "j" Sleep 500ms Type "j"
Sleep 4s
Enter
Sleep 4s

# Explain result
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "Hooray! Our @local@ repository is instantly cleaned up without touching active work." Enter
Sleep 6s

# Cleanup
Sleep 3s
Hide
  Type "tmux capture-pane -p -t git_prune_local_demo:0.2 > /tmp/vhs-out.txt" Enter
  Sleep 1s
  Type "cd /tmp" Enter
  Type "rm -rf /tmp/vhs-repo-prune-local" Enter
Show

