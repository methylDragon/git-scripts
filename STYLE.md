# Architectural & Domain Style Guidelines

This document captures the higher-level design philosophy and domain semantics for `git-scripts`. For syntax, formatting, and linting rules, refer to our `ruff` configurations and `pixi` definitions.

## 1. Data Models (Dataclasses vs Pydantic)

- **Native Dataclasses:** We exclusively use native `@dataclass(frozen=True)` over Pydantic `BaseModel` for internal data structures and models.
- **Why?** For a local CLI utility walking Git graphs, execution speed, immutability, and a low memory footprint are paramount. Pydantic introduces unnecessary runtime coercion overhead for deterministic local data. We prefer static verification via Mypy/Pyright over runtime payload validation.
- **Enums:** We prefer explicit Python `Enum` classes over string literals or `Literal` types for routing application logic (e.g., `RebaseAction`).

## 2. Domain Naming & Side Effects

To maintain a unified and easily understandable domain language across the toolset, we adhere to the following rules for naming models and state objects:

- **The `Result` Suffix:** Use the `Result` suffix (e.g., `TopologyAnalysisResult`, `RemotePruneResult`, `BranchRebaseResult`) **only** for objects that represent the terminal output of an analytical scan, computation, or operation.
- **State vs Result:** Context managers and environmental state-tracking objects (e.g., tracking locked branches across worktrees) should be named `*State` (e.g., `WorktreeState`), not `*Result`.
- **Scope Precision (Branch vs Stack):** Be precise about the scope of the model. For example, `BranchRebaseResult` operates on a *single branch*. Do not name something `Stack*` unless it fundamentally operates on the entire stack collectively.
- **Read vs Write Isolation:** Functions that analyze or query Git state must be pure (e.g., `analyze_`, `get_`, `read_`) and MUST NOT mutate state. Functions that perform mutations (e.g., `execute_`, `apply_`, `push_`) should be clearly demarcated and isolated.

## 3. Type Hinting (Python 3.10+)

We rely heavily on static typing for safety. Since our baseline is Python 3.10+:

- Use the `|` operator for unions (e.g., `str | None` instead of `Optional[str]`, `int | str` instead of `Union[int, str]`).
- Use built-in generics (e.g., `list[str]`, `dict[str, int]`, `set[int]`) instead of importing from the `typing` module (`List`, `Dict`, `Set`).
- Be aggressive with return types, especially for internal helper functions.

## 4. Cyclomatic Complexity Mitigation

We enforce strict constraints on Cyclomatic Complexity (CCN) to ensure maintainability. If a command orchestrator (like `execute_evolve` or `execute_push_prefix`) grows beyond CCN 10-15, we aggressively extract highly cohesive sub-blocks:

- **Isolate Formatting:** Extract purely visual and formatting logic into `_print_*_summary` helper functions.
- **Isolate Data Gathering:** Extract complex data traversal and querying loops into dedicated `_get_*` functions.
- **Isolate Routing:** Extract complex decision trees into `_determine_*_strategy` functions that return strongly-typed `Result` or `Action` models.
