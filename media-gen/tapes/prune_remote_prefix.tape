Output media-gen/media/prune_remote_prefix.gif

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
  Type "python3 media-gen/setup_demo_repo.py --scenario prune-remote --attach" Enter
  Sleep 1s
Show

Sleep 4s

Ctrl+L
Type "Notice the branch topology on the left:" Enter
Type "  - We have a messy @remote@ history with many @demo/@ branches." Enter
Type "  - Some branches were cherry-picked and merged into main," Enter
Type "  - while others are still active." Enter
Sleep 6s

# Run the command
Ctrl+L
Type "Cleaning this up safely is hard without checking every single branch." Enter
Type "Let's use @git batch prune remote -p demo/@ to intelligently clean up!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "git batch prune remote -p demo/"
Sleep 4s
Enter

# Wait for prompt
Sleep 3s

# Explain prompt
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "The tool analyzes our topology and automatically detects obsolete @remote@ branches!" Enter
Type "It categorizes them and warns us if we are deleting unmerged work!" Enter
Type "We'll answer the prompt and select 'Delete all'!" Enter
Sleep 2s

# Answer prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Sleep 4s
Enter
Sleep 4s

# Explain result
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "Hooray! The @remote@ was safely pruned of its obsolete branches." Enter
Sleep 6s

