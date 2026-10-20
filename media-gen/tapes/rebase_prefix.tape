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
  Type "python3 media-gen/setup_demo_repo.py --scenario rebase-prefix --attach" Enter
  Sleep 1s
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
Type "but we can use @git batch rebase -p@ to rebase all stacks matching the @demo/@ prefix at once!" Enter
Enter
Type "*Not shown: rebase conflicts will gracefully pause, giving you the option to resolve them or safely abort the affected stack!" Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "git batch rebase -p demo/"
Sleep 4s
Enter

# Wait for Rebase to Finish
Sleep 4s

# Rebase Explanation Comment
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
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
Sleep 200ms
Type "j" Sleep 500ms Type "j"
Sleep 4s
Enter
Sleep 1s

# Explain Delete effect
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "We deleted the obsolete branches!" Enter
Sleep 4s

# Explain Push Prompt Comment
Ctrl+L
Type "Finally, we are given the option to push the branches we just rebased." Enter
Enter
Type "Since it detects rebased branches, it smartly defaults to @Push all@!" Enter
Type "We'll just hit Enter to confirm." Enter
Sleep 2s

# Switch to command pane to execute push
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Sleep 4s
Enter
Sleep 4s

# Show result
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "Hooray! All branches rebased, preserving identical topology on the new main!" Enter
Type "Obsolete branch @demo/a@ was safely pruned!" Enter
Sleep 6s

