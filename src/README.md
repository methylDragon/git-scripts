# git-scripts Source Architecture

This directory contains the Python source code for `git-scripts`. The architecture decouples presentation, CLI orchestration, and Git operations.

## Module Boundaries

- **`ui.py` (Presentation)**

  - **Responsibility:** Terminal output, user prompts, progress bars, and string formatting.
  - **Boundary:** This module manages `rich` and `questionary` dependencies. It does not execute Git or GitHub operations or hold repository state.

- **`cli.py` (Entrypoint)**

  - **Responsibility:** Typer/Click command signatures and argument parsing.
  - **Boundary:** Maps CLI inputs to the corresponding orchestrator in `cmd/`. Does not implement domain logic.

- **`models.py` (Data)**

  - **Responsibility:** Shared typed dataclasses and enums (e.g., `BranchRebasePlan`, `SingleBranchResult`, `BatchRebaseConfig`, `RebaseStatus`).
  - **Boundary:** Plain data objects used to communicate status and configuration across layers without tightly coupling them.

- **`cmd/` (Orchestrators)**

  - **Responsibility:** High-level command execution, coordination of the UI with domain logic, state tracking, and control flow loops.
  - **Boundary:** Modules (e.g., `rebase_prefix.py`, `evolve.py`, `rebase_stack.py`) parse intent and execute the main CLI operations.
  - **`rebase_orchestrator.py`:** Hosts the centralized `rebase_loop` orchestrator and interactive conflict handlers. Orchestrators in `cmd/` are permitted to receive the `ui` instance, manage worktree state managers, and display interactive output. They rely on domain functions returning actionable status enums instead of raw strings.

- **`gh/` (GitHub API)**

  - **Responsibility:** `gh` CLI command execution.
  - **Boundary:** Returns data or raises exceptions on failure. Does not interact with the terminal.

- **`git/` (Git Domain Subsystem)**

  - **Responsibility:** `pygit2` and Git subprocess wrappers. Pure domain logic implementations.
  - **Boundary:** Functions return data, data models, status enums, or raise explicit exceptions (`GitExecutionError`). They **strictly do not** accept `ui` instances or print to the terminal.
  - **`core.py`:** Base command execution wrappers.
  - **`reads.py`**: Non-mutating repository queries (e.g. log extraction, status checks).
  - **`rebase.py`**: Mutating Git operations for rebasing (onto, continue, abort).
  - **`rebase_plan.py`**: Calculates the topological actions (`RebaseAction`) needed to rebase a branch and executes those plans.
  - **`remote.py`**: Network-bound Git operations (fetch, pull, push, pruning).
  - **`topology.py`**: Commit history, obsolescence calculation, and branch co-location synchronization.
  - **`worktrees.py`**: Detachment and locking for multi-worktree execution.
  - **`parallel.py`**: Thread-pool execution primitives.
