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
  Type "python3 media-gen/setup_demo_repo.py --scenario evolve --attach" Enter
  Sleep 1s
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
Sleep 200ms

Type "git commit --amend -m 'a (amended)'"
Sleep 4s
Enter
Sleep 2s

Ctrl+B
Sleep 500ms
Up
Sleep 200ms

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
Sleep 200ms

Type "git evolve"
Sleep 4s
Enter
Sleep 2s

# Explain prompt
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "The tool detected the orphaned branches (@demo/stack-tip-1@ and @demo/stack-tip-2@) and figured out where they need to go!" Enter
Type "We'll confirm the automatic rebase by typing 'y' and hitting Enter." Enter
Sleep 2s

# Answer prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "y"
Sleep 4s
Enter
Sleep 6s

Ctrl+B
Sleep 500ms
Up
Sleep 200ms

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
Sleep 200ms
Sleep 4s
Enter
Sleep 6s

