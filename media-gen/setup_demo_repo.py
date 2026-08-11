#!/usr/bin/env python3
"""Setup the fake git repository for VHS tape demonstrations."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], check: bool = True, cwd: str | None = None):
    """Run a shell command."""
    subprocess.run(cmd, check=check, cwd=cwd)


def commit(repo_path: Path, msg: str):
    """Write a text file and commit it to simulate work."""
    (repo_path / f"{msg}.txt").write_text(msg)
    run_cmd(["git", "add", f"{msg}.txt"])
    run_cmd(["git", "commit", "-m", msg])


def checkout(branch: str, create: bool = False):
    """Check out a branch, optionally creating it first."""
    if create:
        run_cmd(["git", "checkout", "-b", branch])
    else:
        run_cmd(["git", "checkout", branch])


def build_base_topology(repo_path: Path):
    """Manually rebuild a base topological structure.

    Stack Layout:
    main
    ├── demo/a
    │   └── demo/a-b
    │       └── demo/a-b-c (tip)
    └── demo/d
        └── demo/d-e
            └── demo/d-e-f
                ├── demo/d-e-f-g
                │   └── demo/d-e-f-g-h
                │       └── demo/d-e-f-g-h-i (tip)
                └── demo/d-e-f-j
                    └── demo/d-e-f-j-k
                        └── demo/d-e-f-j-k-l (tip)
    """
    os.chdir(repo_path)
    run_cmd(["git", "init"])
    run_cmd(["git", "config", "user.name", "Test User"])
    run_cmd(["git", "config", "user.email", "test@example.com"])
    run_cmd(["git", "commit", "--allow-empty", "-m", "Initial commit"])
    run_cmd(["git", "branch", "-m", "main"])

    checkout("main")
    commit(repo_path, "main-base")

    # Chain A
    checkout("demo/a", create=True)
    commit(repo_path, "a")
    checkout("demo/a-b", create=True)
    commit(repo_path, "b")
    checkout("demo/a-b-c", create=True)
    commit(repo_path, "c")

    # Chain D
    checkout("main")
    checkout("demo/d", create=True)
    commit(repo_path, "d")
    checkout("demo/d-e", create=True)
    commit(repo_path, "e")
    checkout("demo/d-e-f", create=True)
    commit(repo_path, "f")

    # Fork G
    checkout("demo/d-e-f-g", create=True)
    commit(repo_path, "g")
    checkout("demo/d-e-f-g-h", create=True)
    commit(repo_path, "h")
    checkout("demo/d-e-f-g-h-i", create=True)
    commit(repo_path, "i")

    # Fork J
    checkout("demo/d-e-f")
    checkout("demo/d-e-f-j", create=True)
    commit(repo_path, "j")
    checkout("demo/d-e-f-j-k", create=True)
    commit(repo_path, "k")
    checkout("demo/d-e-f-j-k-l", create=True)
    commit(repo_path, "l")

    checkout("main")


def setup_rebase_prefix_scenario(repo_dir: Path):
    """Establish obsolete remote commits and detached local stacks."""
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "--all"])

    checkout("main")
    run_cmd(["git", "branch", "-m", "main", "main-base"])
    checkout("main-base")
    run_cmd(["git", "checkout", "-b", "main-update"])

    commit(repo_dir, "main-filler-1")
    run_cmd(["git", "cherry-pick", "--strategy-option=theirs", "demo/a"])

    commit(repo_dir, "main-filler-2")
    commit(repo_dir, "main-filler-3")

    run_cmd(["git", "commit", "--allow-empty", "-m", "main-update"])
    run_cmd(["git", "branch", "-m", "main-update", "main"])
    checkout("demo/a")


def setup_push_prefix_scenario(repo_dir: Path):  # noqa: D103
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "main"])
    checkout("demo/a-b-c")


def setup_push_stack_scenario(repo_dir: Path):  # noqa: D103
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "main"])
    checkout("demo/d-e-f-g-h-i")


def setup_prune_local_scenario(repo_dir: Path):  # noqa: D103
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "--all"])
    run_cmd(
        [
            "git",
            "push",
            "origin",
            "--delete",
            "demo/a-b-c",
            "demo/d-e",
            "demo/d-e-f-j-k",
        ]
    )
    checkout("main")


def setup_prune_remote_scenario(repo_dir: Path):  # noqa: D103
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "--all"])
    checkout("main")
    run_cmd(["git", "cherry-pick", "demo/a"])
    run_cmd(["git", "push", "origin", "main"])
    checkout("main")


def setup_evolve_scenario(repo_dir: Path):  # noqa: D103
    os.chdir(repo_dir)
    run_cmd(["git", "init"])
    run_cmd(["git", "config", "user.name", "Test User"])
    run_cmd(["git", "config", "user.email", "test@example.com"])
    run_cmd(["git", "commit", "--allow-empty", "-m", "Initial commit"])
    run_cmd(["git", "branch", "-m", "main"])

    commit(repo_dir, "base")
    checkout("demo/stack-base", create=True)
    commit(repo_dir, "a")

    checkout("demo/stack-tip-1", create=True)
    commit(repo_dir, "b")

    checkout("demo/stack-base")
    checkout("demo/stack-tip-2", create=True)
    commit(repo_dir, "c")

    checkout("demo/stack-base")


def setup_gh_align_scenario(repo_dir: Path):
    """Setup scenario for git gh-align-pr-bases-and-sync-stacks."""
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "--all"])
    checkout("demo/d-e-f")


def create_wrappers(repo_dir: Path):
    """Add executable scripts to path to intercept git commands."""
    project_root = Path(__file__).resolve().parent.parent
    src_dir = (project_root / "src").resolve()

    commands = [
        "evolve",
        "gh-align-pr-bases-and-sync-stacks",
        "prune-local",
        "prune-remote-prefix",
        "push-prefix",
        "push-stack",
        "rebase-prefix",
    ]

    for cmd in commands:
        wrapper_path = repo_dir / f"git-{cmd}"
        script = (
            f"#!/bin/bash\n"
            f'export PATH="{repo_dir}:$PATH"\n'
            f'export PYTHONPATH="{src_dir}"\n'
            f'{sys.executable} -m git_scripts.cli {cmd} "$@"\n'
        )
        wrapper_path.write_text(script)
        wrapper_path.chmod(0o755)

    # Mock gh for gh-align-pr-bases-and-sync-stacks
    gh_mock = repo_dir / "gh"
    gh_mock.write_text("""#!/bin/bash
echo "Mocking gh $@" >> /tmp/gh_mock.log
if [[ "$1" == "auth" && "$2" == "status" ]]; then
    exit 0
elif [[ "$1" == "--version" ]]; then
    echo "gh version 2.0.0"
    exit 0
elif [[ "$1" == "pr" && "$2" == "list" ]]; then
    echo (
        '[{"headRefName": "demo/d-e-f", "baseRefName": "main", '
        '"url": "https://github.com/demo/pull/3", "number": 3}, '
        '{"headRefName": "demo/d-e", "baseRefName": "main", '
        '"url": "https://github.com/demo/pull/2", "number": 2}, '
        '{"headRefName": "demo/d", "baseRefName": "main", '
        '"url": "https://github.com/demo/pull/1", "number": 1}]'
    )
elif [[ "$1" == "pr" && "$2" == "view" ]]; then
    echo '{"baseRefName": "main"}'
else
    echo "Success"
    sleep 0.5
fi
""")
    gh_mock.chmod(0o755)


def setup_demo_repo():
    """Create and set up the fake git repo topology."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", default="rebase-prefix", help="Scenario to setup"
    )
    args = parser.parse_args()

    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    os.environ["GIT_CONFIG_SYSTEM"] = "/dev/null"

    repo_dir = Path(f"/tmp/vhs-repo-{args.scenario}")
    remote_dir = Path(f"/tmp/vhs-remote-{args.scenario}")
    if repo_dir.exists():
        shutil.rmtree(repo_dir)
    if remote_dir.exists():
        shutil.rmtree(remote_dir)

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    remote_dir.mkdir(parents=True, exist_ok=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    # Setup fake remote
    run_cmd(["git", "init", "--bare"], cwd=str(remote_dir))

    os.chdir(repo_dir)
    # Add fake remote
    run_cmd(["git", "init"])
    run_cmd(["git", "remote", "add", "origin", str(remote_dir)])

    scenarios = {
        "rebase-prefix": setup_rebase_prefix_scenario,
        "push-prefix": setup_push_prefix_scenario,
        "push-stack": setup_push_stack_scenario,
        "prune-local": setup_prune_local_scenario,
        "prune-remote": setup_prune_remote_scenario,
        "evolve": setup_evolve_scenario,
        "gh-align": setup_gh_align_scenario,
    }

    if args.scenario in scenarios:
        scenarios[args.scenario](repo_dir)
    else:
        print(f"Unknown scenario {args.scenario}")
        sys.exit(1)

    create_wrappers(repo_dir)

    print(f"Repo setup complete for {args.scenario} in {repo_dir.resolve()}")
    print("\nResulting Git Tree:")
    run_cmd(
        [
            "git",
            "log",
            "--graph",
            "--oneline",
            "--all",
            "--decorate",
            "--color",
        ]
    )


if __name__ == "__main__":
    setup_demo_repo()
