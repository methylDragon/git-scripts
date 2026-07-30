# Contributing to git-scripts

Thank you for your interest in contributing to `git-scripts`! This repository is built as a highly-performant, typed Python implementation of Git stack management scripts.

## Architecture

This tool uses a Hybrid Architecture separating graph analysis from native git mutations. Please see [ARCHITECTURE.md](ARCHITECTURE.md) for full details on the system structure.

## Environment Setup

This project uses `pixi` for environment and dependency management.

1. **Install Pixi**: <https://pixi.sh/>
1. **Initialize workspace**: Run `pixi install`. This automatically handles C-extensions (like `libgit2` for `pygit2`) and sets up `pydantic`, `rich`, and testing tools.

## Tasks

We provide convenient `pixi` tasks for development:

- **Lint**: `pixi run lint` (runs Ruff)
- **Format**: `pixi run format` (runs Ruff formatter)
- **Test**: `pixi run test` (runs PyTest with absltest)

## Code Standards

- **Pydantic**: Use Pydantic models (like `StackAnalysisResult` in `models.py`) to pass strongly-typed data between the analysis and execution phases.
- **Pure Functions**: Keep the analysis functions pure where possible. Tests utilize temporary physical git repos to validate graph logic.
- **Subprocess Shelling**: Only use `subprocess` in `git/writes.py` for mutating state. Graph reads belong in `git/reads.py` using `pygit2`.

We welcome pull requests!
