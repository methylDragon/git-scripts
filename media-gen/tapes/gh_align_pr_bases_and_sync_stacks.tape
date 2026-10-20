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
  Type "python3 media-gen/setup_demo_repo.py --scenario gh-align --attach" Enter
  Sleep 1s
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
Type "Let's use @git gh align@ to do it automatically via the GitHub API!" Enter
Enter
Type "It will also detect and let us create PRs for branches that don't have them." Enter
Sleep 2s

# Switch to command pane
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "git gh align"
Sleep 4s
Enter

# Wait for PR Creation prompt
Sleep 3s

# Explain PR creation selection
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "The tool detected branches missing PRs. Notice we can choose which ones to create PRs for." Enter
Enter
Type "Suppose we only want to send PRs up to @demo/d-e-f@ (e.g., because we're still developing downstream branches)," Enter
Type "we can only select @demo/d-e-f@ by pressing Space, then Enter." Enter
Sleep 2s

# Answer PR Creation prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
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
Sleep 200ms
Ctrl+L
Type "The tool identified the branches that need to be synced, and prepared a draft PR for our missing branch (@demo/d-e-f@)!" Enter
Type "We'll confirm applying the PR base changes by typing 'y' and hitting Enter." Enter
Sleep 2s

# Answer alignment prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "y"
Sleep 4s
Enter

# Wait for edits and creates to finish (takes ~2s) and stack sync prompt to appear
Sleep 4s

# Explain stack sync prompt
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "Since we have multiple branches, it asks if we want to synchronize our GitHub stack using the @gh stack@ extension." Enter
Type "We'll confirm this by typing 'y' and hitting Enter." Enter
Sleep 2s

# Answer stack sync prompt
Ctrl+B
Sleep 500ms
Down
Sleep 200ms
Type "y"
Sleep 4s
Enter

# Wait for stack sync to finish
Sleep 6s

# Explain result
Ctrl+B
Sleep 500ms
Up
Sleep 200ms
Ctrl+L
Type "Hooray! The tool used the GitHub API to seamlessly create missing PRs, align all PR bases, and sync our GitHub stack!" Enter
Type "Our local topology is perfectly mirrored on the remote." Enter
Sleep 6s

