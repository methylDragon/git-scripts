# Architecture

The `git-scripts` project utilizes a **Hybrid Architecture** that splits the workload into two distinct domains: in-memory analysis and state mutation. This approach maximizes performance for repository traversal while relying on the safety of the native Git CLI for altering the repository's state.

## 1. The "Brain" (Read / Analysis)

- **Location:** `src/git_scripts/git/reads.py`
- **Powered by:** `pygit2`

Graph traversals, branch tip detection, merge base calculations, and cut/sync point logic happen entirely in memory using `pygit2`. This allows for extremely fast C-level iterations over the commit graph without paying the process startup overhead of calling Git commands repeatedly.

The analysis phase is designed to be pure and side-effect free. It analyzes the commit history and decides what action is required for a branch or stack.

## 2. The "Muscle" (Write / Execution)

- **Location:** `src/git_scripts/git/writes.py`
- **Powered by:** Python `subprocess` (wrapping native Git CLI)

Mutating operations—such as rebasing, deleting branches, or checking out worktrees—are delegated to the native Git engine. This ensures complex, potentially destructive operations (e.g., `git rebase --update-refs`) behave exactly as expected and handles edge cases, locking, and configuration setups that the native Git CLI already perfected.

## 3. Data Transfer Models

- **Location:** `src/git_scripts/models.py`
- **Powered by:** `pydantic`

To bridge the gap between the "Brain" and the "Muscle", the analysis phase returns highly structured and strictly typed Pydantic models (like `StackAnalysisResult`). The command runners in `src/git_scripts/cmd/` (such as `rebase_prefix.py` or `evolve.py`) interpret these objects and issue the corresponding shell execution commands through the writes module.
