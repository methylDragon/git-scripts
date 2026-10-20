Output media-gen/media/push_prefix.gif

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
  Type "python3 media-gen/setup_demo_repo.py --scenario push-prefix --attach" Enter
  Sleep 1s
Show

Sleep 4s

Ctrl+L
Type "Notice the branch topology on the left:" Enter
Type "  - We have multiple local branches prefixed with @demo/@." Enter
Type "  - None of them exist on the remote repository yet." Enter
Sleep 6s

# Run the command
Ctrl+L
Type "Pushing them all up one by one would be tedious, and we might forget some." Enter
Type "Let's use @git batch push -p demo/ --force-with-lease@ to push them all at once safely!" Enter
Enter
Type "We can also pass arbitrary git arguments to the push command!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "git batch push -p demo/ --force-with-lease"
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
Type "The tool detected all the unpushed branches (e.g., @demo/a-b-c@, @demo/d-e-f-g-h-i@, etc.)!" Enter
Type "We'll confirm the push for all of them by selecting 'Push all'." Enter
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
Type "Hooray! Notice how all the local branches were successfully pushed and linked to their tracking remote branches." Enter
Sleep 6s

