# Media Generation

This directory contains scripts and VHS tapes to generate demo GIFs for `git-scripts`.

## Tools Used

- **[vhs](https://github.com/charmbracelet/vhs)**: Used to script and record the terminal interactions.
- **git log (or git-graph)**: Used to visually display the branching tree before and after command executions.

## Scenarios

- `git batch rebase --prefix <pfx>`: Rebases all branch stacks matching a prefix onto the target branch.
  ![git batch rebase --prefix demo](media/rebase_prefix.gif)

- `git batch push`: Pushes all branches in the current stack to the remote.
  ![git batch push demo](media/push_stack.gif)

- `git batch push --prefix <pfx>`: Pushes all local branches matching a prefix to the remote repository.
  ![git batch push --prefix demo](media/push_prefix.gif)

- `git batch prune local`: Prunes local branches whose remote tracking branches are gone.
  ![git batch prune local demo](media/prune_local.gif)

- `git batch prune remote --prefix <pfx>`: Prunes remote branches matching a prefix that are merged into the target branch.
  ![git batch prune remote demo](media/prune_remote_prefix.gif)

- `git evolve`: Evolves local branches after upstream history was rewritten.
  ![git evolve demo](media/evolve.gif)

- `git gh align`: Aligns GitHub PR bases and syncs local stacks.
  ![git gh align demo](media/gh_align_pr_bases_and_sync_stacks.gif)

## Generating GIFs

To generate the GIFs, you need `vhs` and `pixi` installed.

```bash
# Run all of them in parallel
pixi run media-gen-all

# Or run a specific tape
pixi run media-gen media-gen/tapes/rebase_prefix.tape
```
