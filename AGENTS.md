# Agent Context Guidelines

This file is specifically for AI agents (like Roo, Claude, etc.) operating in this repository to prevent hallucinations, setup failures, and regressions of critical safety features.

## 1. Environment & Tooling

- **Package Manager:** This repository uses `pixi` for dependency and environment management.
  - **DO NOT** use `pip install` or create generic virtual environments.
  - Use `pixi run lint`, `pixi run format`, and `pixi run test` for standard operations.
- **Python Constraints:** The project targets Python 3.10+. Always prefer structural pattern matching (`match/case`) over long `if/elif` chains for basic routing.
- **Dependencies:** Do not arbitrarily add new packages to `pixi.toml` unless strictly necessary. Rely on the standard library or existing dependencies (`pygit2`, `rich`, `questionary`) where possible.

## 2. Writing Code

- **Shared Guidelines:** Before proposing architectural changes or adding new data structures, you MUST read `STYLE.md` to understand our exact naming conventions (e.g., when to use `Result` vs `State`), type hinting rules, and model preferences (Dataclasses vs Pydantic).
- **Linting & Complexity:** DO NOT add `noqa` comments to bypass line length or complexity rules (e.g., `E501` or `C901`). You must instead refactor the code to comply with the rules.

## 3. Critical Safety Guardrails

- **Git Pruning:** The concept of "pruning" in this repository implies safe garbage collection. If you are asked to modify a prune command (like `git-prune-remote-prefix`), **never short-circuit the obsolescence check**.
  - Even if aggressive flags like `--also-prune-no-local` are passed, the tool must verify obsolescence.
  - Unmerged branches must ALWAYS be bucketed separately and presented to the user with a high-visibility warning prompt. Silent deletion of unmerged remote branches is a catastrophic anti-pattern.
- **Cross-Worktree Operations:** Git locks branches checked out in other worktrees. If modifying batch branch operations (like batch rebase), you must use the `manage_worktrees` context manager to safely detach those branches before operating on them, and reattach them afterward.
- **Testing:** When writing or modifying features, you must ensure that associated tests are updated or created. Do not delete test logs during active test debugging.
