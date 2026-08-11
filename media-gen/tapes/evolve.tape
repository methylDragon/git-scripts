Output media-gen/media/evolve.gif

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
  Type "tmux kill-session -t git_evolve_demo 2>/dev/null || true" Enter
  Type "rm -rf /tmp/vhs-repo-evolve" Enter
  Type "pixi run -q python media-gen/setup_demo_repo.py --scenario evolve > /dev/null" Enter
  Type "export GIT_CONFIG_GLOBAL=/dev/null" Enter
  Type "export GIT_CONFIG_SYSTEM=/dev/null" Enter
  Type "export PATH=/tmp/vhs-repo-evolve:$PATH" Enter
  Type "tmux new-session -s git_evolve_demo -d" Enter
  Type "tmux set -t git_evolve_demo status on" Enter
  Type "tmux set -t git_evolve_demo status-style 'bg=default,fg=white'" Enter
  Type 'tmux set -t git_evolve_demo status-left ""' Enter
  Type 'tmux set -t git_evolve_demo window-status-current-format ""' Enter
  Type 'tmux set -t git_evolve_demo window-status-format ""' Enter
  Type 'tmux set -t git_evolve_demo status-right "demo: git evolve "' Enter
  Type "tmux set -t git_evolve_demo pane-border-style 'fg=colour239'" Enter
  Type "tmux set -t git_evolve_demo pane-active-border-style 'fg=#ffcc66'" Enter
  Type "tmux split-window -t git_evolve_demo -v -p 85" Enter
  Type "tmux select-pane -t git_evolve_demo:0.1" Enter
  Type "tmux split-window -t git_evolve_demo:0.1 -h -p 50" Enter
  Type "tmux attach-session -t git_evolve_demo" Enter
  Ctrl+L

  # Setup Left Pane (Graph)
  Ctrl+B
  Sleep 500ms
  Left
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-evolve" Enter
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
  
  Type "clear; pixi run -q python media-gen/vhs_utils.py banner 'git evolve' --subtext 'Evolves local branches after upstream history was rewritten.'; pixi run -q python media-gen/vhs_utils.py comment_reader" Enter

  # Setup Bottom Right Pane (Commands)
  Ctrl+B
  Sleep 500ms
  Down
  Sleep 500ms
  Type "export PATH=/tmp/vhs-repo-gh-align:$PATH" Enter
  Type "cd /tmp/vhs-repo-evolve" Enter
  Type 'export PS1="> "' Enter
  Ctrl+L

  # Initial State Exploration
  Ctrl+B
  Sleep 500ms
  Up
Show

Sleep 4s

Ctrl+L
Type "Here is a forking branch stack: @demo/stack-base@ -> @demo/stack-tip-1@ and @demo/stack-tip-2@" Enter
Type "Let's simulate a history rewrite by amending the current commit." Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down

Type "git commit --amend -m 'a (amended)'"
Sleep 4s
Enter
Sleep 2s

Ctrl+B
Sleep 500ms
Up

Ctrl+L
Type "Oh no! We amended the base commit, rewriting history!" Enter
Type "Notice how the two child branches are now 'orphaned' and point to the old commit." Enter
Sleep 6s

Ctrl+L
Type "Ideally we want the orphaned branches to 'evolve' to point to the new commit." Enter
Enter
Type "Normally this requires interactive rebasing each child individually." Enter
Type "But we can use @git evolve@ to automatically fix the entire forked stack!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down

Type "git evolve"
Sleep 4s
Enter
Sleep 2s

# Explain prompt
Ctrl+B
Sleep 500ms
Up
Ctrl+L
Type "The tool detected the orphaned branches (@demo/stack-tip-1@ and @demo/stack-tip-2@) and figured out where they need to go!" Enter
Type "We'll confirm the automatic rebase by typing 'y' and hitting Enter." Enter
Sleep 2s

# Answer prompt
Ctrl+B
Sleep 500ms
Down
Type "y"
Sleep 4s
Enter
Sleep 6s

Ctrl+B
Sleep 500ms
Up

Ctrl+L
Type "Hooray! @git evolve@ calculated the history rewrite," Enter
Type "and automatically rebased all orphaned children (even across forks) back onto the new HEAD." Enter
Sleep 6s

# Explain push prompt

Ctrl+L
Type "Finally, we are prompted to push our branches to the remote." Enter
Type "We'll select 'Push all' by hitting Enter." Enter
Sleep 2s

# Answer push prompt
Ctrl+B
Sleep 500ms
Down
Sleep 4s
Enter
Sleep 4s

# Cleanup
Sleep 3s
Hide
  Type "tmux capture-pane -p -t git_evolve_demo:0.2 > /tmp/vhs-out.txt" Enter
  Sleep 1s
  Type "cd /tmp" Enter
  Type "rm -rf /tmp/vhs-repo-evolve" Enter
Show

