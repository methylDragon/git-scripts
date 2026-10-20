Output media-gen/media/push_stack.gif

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
  Type "python3 media-gen/setup_demo_repo.py --scenario push-stack --attach" Enter
  Sleep 1s
Show

Sleep 4s

Ctrl+L
Type "Notice the branch topology on the left:" Enter
Type "  - We are currently checked out on the tip of a deeply nested stack of branches (@demo/d-e-f-g-h-i@)." Enter
Type "  - None of these branches exist on the remote repository yet." Enter
Sleep 6s

# Run the command
Ctrl+L
Type "We want to push the entire stack, but standard @git push@ will only push the current branch." Enter
Type "Let's use @git batch push@ to push the entire lineage up to trunk in topological order!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "git batch push"
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
Type "The tool detected the entire lineage of branches up to trunk! (e.g., @demo/d@ ... @demo/d-e-f-g-h-i@)" Enter
Type "We'll confirm pushing all of them by selecting 'Push all'." Enter
Sleep 2s

# Answer prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Sleep 4s
Enter
Sleep 6s

# Push Explanation Comment
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "Hooray! The entire stack leading up to our current branch was safely pushed in the correct order!" Enter
Sleep 6s

