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
  Type "python3 media-gen/setup_demo_repo.py --scenario prune-local --attach" Enter
  Sleep 1s
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
Type "Let's use @git batch prune local@ to perform an obsolescence check and safely clean up!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "git batch prune local"
Sleep 4s
Enter

# Wait for Prompt
Sleep 2s

# Explain prompt
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "The tool instantly identifies any local branch whose remote tracking branch no longer exists! (e.g., @demo/a-b-c@, @demo/d-e@, @demo/d-e-f-j-k@)" Enter
Type "It provides an interactive prompt so we can safely review and select which ones to delete." Enter
Type "We'll answer the prompt and select 'Delete all'!" Enter
Sleep 2s

# Answer prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "j" Sleep 500ms Type "j"
Sleep 4s
Enter
Sleep 4s

# Explain result
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "Hooray! Our @local@ repository is instantly cleaned up without touching active work." Enter
Sleep 6s

