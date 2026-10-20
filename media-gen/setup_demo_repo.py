#!/usr/bin/env python3
"""Setup fake git repositories and isolated tmux sessions for VHS demos."""

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PIXI_PYTHON = PROJECT_ROOT / ".pixi" / "envs" / "default" / "bin" / "python"
PYTHON_EXE = str(
    _PIXI_PYTHON if _PIXI_PYTHON.exists() else Path(sys.executable)
)


@dataclass(frozen=True)
class DemoScenarioConfig:
    """Configuration metadata for a single VHS demo scenario."""

    scenario: str
    status_right: str
    banner_title: str
    banner_subtext: str
    demo_env: bool = False


SCENARIO_CONFIGS: dict[str, DemoScenarioConfig] = {
    "rebase-prefix": DemoScenarioConfig(
        scenario="rebase-prefix",
        status_right="demo: git batch rebase -p ",
        banner_title="git batch rebase",
        banner_subtext=(
            "Rebases all stacks matching prefix onto target. "
            "Preserves topology; skips commits already squashed upstream."
        ),
    ),
    "push-stack": DemoScenarioConfig(
        scenario="push-stack",
        status_right="demo: git batch push ",
        banner_title="git batch push",
        banner_subtext=(
            "Pushes all branches in the current stack to the remote."
        ),
    ),
    "push-prefix": DemoScenarioConfig(
        scenario="push-prefix",
        status_right="demo: git batch push -p ",
        banner_title="git batch push -p",
        banner_subtext=(
            "Pushes all local branches matching a prefix "
            "to the remote repository."
        ),
    ),
    "prune-local": DemoScenarioConfig(
        scenario="prune-local",
        status_right="demo: git batch prune local ",
        banner_title="git batch prune local",
        banner_subtext=(
            "Prunes local branches after an obsolescence check "
            "(fetch --prune)."
        ),
    ),
    "prune-remote": DemoScenarioConfig(
        scenario="prune-remote",
        status_right="demo: git batch prune remote ",
        banner_title="git batch prune remote",
        banner_subtext=(
            "Prunes remote branches with a prefix and checks for obsoletion."
        ),
    ),
    "gh-align": DemoScenarioConfig(
        scenario="gh-align",
        status_right="demo: git gh align ",
        banner_title="git gh align",
        banner_subtext="Aligns PR bases and syncs local stacks.",
        demo_env=True,
    ),
    "evolve": DemoScenarioConfig(
        scenario="evolve",
        status_right="demo: git evolve ",
        banner_title="git evolve",
        banner_subtext=(
            "Evolves local branches after upstream history was rewritten."
        ),
    ),
}


def get_tmux_socket_path(scenario: str) -> Path:
    """Returns the isolated tmux socket path for a demo scenario."""
    return Path(f"/tmp/vhs-tmux-{scenario}.sock")


def get_banner_ready_path(scenario: str) -> Path:
    """Returns the readiness marker path for pane 0.0 of a demo scenario."""
    return Path(f"/tmp/vhs-banner-ready-{scenario}")


def run_cmd(
    cmd: list[str], *, check: bool = True, cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a shell command with captured text output."""
    return subprocess.run(
        cmd,
        check=check,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def commit(repo_path: Path, msg: str) -> None:
    """Write a text file and commit it to simulate work."""
    (repo_path / f"{msg}.txt").write_text(msg, encoding="utf-8")
    run_cmd(["git", "add", f"{msg}.txt"], cwd=str(repo_path))
    run_cmd(["git", "commit", "-m", msg], cwd=str(repo_path))


def checkout(
    branch: str, *, create: bool = False, cwd: str | None = None
) -> None:
    """Check out a branch, optionally creating it first."""
    if create:
        run_cmd(["git", "checkout", "-b", branch], cwd=cwd)
    else:
        run_cmd(["git", "checkout", branch], cwd=cwd)


def build_base_topology(repo_path: Path) -> None:
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
    run_cmd(["git", "init", "-b", "main"])
    run_cmd(["git", "config", "user.name", "Test User"])
    run_cmd(["git", "config", "user.email", "test@example.com"])
    run_cmd(["git", "commit", "--allow-empty", "-m", "Initial commit"])
    run_cmd(["git", "branch", "-M", "main"])

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


def setup_rebase_prefix_scenario(repo_dir: Path) -> None:
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


def setup_push_prefix_scenario(repo_dir: Path) -> None:
    """Set up unpushed demo/* branches for git batch push -p."""
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "main"])
    checkout("demo/a-b-c")


def setup_push_stack_scenario(repo_dir: Path) -> None:
    """Set up an unpushed linear stack for git batch push."""
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "main"])
    checkout("demo/d-e-f-g-h-i")


def setup_prune_local_scenario(repo_dir: Path) -> None:
    """Set up local branches whose upstream tracking branches were deleted."""
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


def setup_prune_remote_scenario(repo_dir: Path) -> None:
    """Set up remote branches where demo/a was cherry-picked into main."""
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "--all"])
    checkout("main")
    run_cmd(["git", "cherry-pick", "demo/a"])
    run_cmd(["git", "push", "origin", "main"])
    checkout("main")


def setup_evolve_scenario(repo_dir: Path) -> None:
    """Set up a two-tip forked stack for git evolve."""
    os.chdir(repo_dir)
    run_cmd(["git", "init", "-b", "main"])
    run_cmd(["git", "config", "user.name", "Test User"])
    run_cmd(["git", "config", "user.email", "test@example.com"])
    run_cmd(["git", "commit", "--allow-empty", "-m", "Initial commit"])
    run_cmd(["git", "branch", "-M", "main"])

    commit(repo_dir, "base")
    checkout("demo/stack-base", create=True)
    commit(repo_dir, "a")

    checkout("demo/stack-tip-1", create=True)
    commit(repo_dir, "b")

    checkout("demo/stack-base")
    checkout("demo/stack-tip-2", create=True)
    commit(repo_dir, "c")

    checkout("demo/stack-base")


def setup_gh_align_scenario(repo_dir: Path) -> None:
    """Setup scenario for git gh align."""
    build_base_topology(repo_dir)
    run_cmd(["git", "push", "-u", "origin", "--all"])
    checkout("demo/d-e-f")


def create_wrappers(repo_dir: Path) -> None:
    """Add executable scripts to path to intercept git commands."""
    src_dir = (PROJECT_ROOT / "src").resolve()

    commands = [
        "batch",
        "evolve",
        "gh",
        "gk",
    ]

    for cmd in commands:
        wrapper_path = repo_dir / f"git-{cmd}"
        script = (
            "#!/bin/bash\n"
            f'export PATH="{repo_dir}:$PATH"\n'
            f'export PYTHONPATH="{src_dir}"\n'
            f'{shlex.quote(PYTHON_EXE)} -m git_scripts.cli {cmd} "$@"\n'
        )
        wrapper_path.write_text(script, encoding="utf-8")
        wrapper_path.chmod(0o755)

    gh_pr_list_json = (
        '[{"headRefName": "demo/d-e-f", "baseRefName": "main", '
        '"url": "https://github.com/demo/pull/3", "number": 3}, '
        '{"headRefName": "demo/d-e", "baseRefName": "main", '
        '"url": "https://github.com/demo/pull/2", "number": 2}, '
        '{"headRefName": "demo/d", "baseRefName": "main", '
        '"url": "https://github.com/demo/pull/1", "number": 1}]'
    )
    gh_mock = repo_dir / "gh"
    gh_mock.write_text(
        f"""#!/bin/bash
if [[ "$1" == "auth" && "$2" == "status" ]]; then
    exit 0
elif [[ "$1" == "--version" ]]; then
    echo "gh version 2.0.0"
    exit 0
elif [[ "$1" == "pr" && "$2" == "list" ]]; then
    echo '{gh_pr_list_json}'
elif [[ "$1" == "pr" && "$2" == "view" ]]; then
    echo '{{"baseRefName": "main"}}'
else
    echo "Success"
    sleep 0.5
fi
""",
        encoding="utf-8",
    )
    gh_mock.chmod(0o755)


def cleanup_scenario(scenario: str) -> None:
    """Kill the isolated tmux server and remove temporary repo directories."""
    sock_path = get_tmux_socket_path(scenario)
    ready_path = get_banner_ready_path(scenario)
    if sock_path.exists():
        run_cmd(["tmux", "-S", str(sock_path), "kill-server"], check=False)
        sock_path.unlink(missing_ok=True)
    ready_path.unlink(missing_ok=True)
    Path(f"/tmp/vhs-out-{scenario}.txt").unlink(missing_ok=True)

    for prefix in ("vhs-repo-", "vhs-remote-"):
        target_dir = Path(f"/tmp/{prefix}{scenario}")
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)


def _configure_tmux_options(sock: str, cfg: DemoScenarioConfig) -> None:
    """Configure status bar, repeat-time, and deterministic pane bindings."""
    tmux_cmds = [
        ["set", "-g", "repeat-time", "0"],
        ["set", "-s", "escape-time", "0"],
        ["set", "-t", "vhs_demo", "status", "on"],
        ["set", "-g", "status-right-length", "100"],
        ["set", "-t", "vhs_demo", "status-style", "bg=default,fg=white"],
        ["set", "-t", "vhs_demo", "status-left", ""],
        ["set", "-t", "vhs_demo", "window-status-current-format", ""],
        ["set", "-t", "vhs_demo", "window-status-format", ""],
        ["set", "-t", "vhs_demo", "status-right", cfg.status_right],
        ["set", "-t", "vhs_demo", "pane-border-style", "fg=colour239"],
        ["set", "-t", "vhs_demo", "pane-active-border-style", "fg=#ffcc66"],
        ["bind-key", "Up", "select-pane", "-t", "vhs_demo:0.0"],
        ["bind-key", "Down", "select-pane", "-t", "vhs_demo:0.2"],
        ["bind-key", "Left", "select-pane", "-t", "vhs_demo:0.1"],
        ["bind-key", "Right", "select-pane", "-t", "vhs_demo:0.2"],
        [
            "set-hook",
            "-t",
            "vhs_demo",
            "client-attached",
            "resize-pane -t vhs_demo:0.0 -y 6",
        ],
    ]
    batched_args = [tok for subcmd in tmux_cmds for tok in (*subcmd, ";")][:-1]
    run_cmd(["tmux", "-S", sock, *batched_args])


def _wait_for_tmux_panes_ready(
    sock: str, ready_path: Path, timeout_sec: float = 15.0
) -> None:
    """Poll until the banner, watch graph, and shell prompt are ready."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if ready_path.exists():
            graph_out = run_cmd(
                [
                    "tmux",
                    "-S",
                    sock,
                    "capture-pane",
                    "-p",
                    "-t",
                    "vhs_demo:0.1",
                ],
                check=False,
            ).stdout
            if "main" in graph_out and "demo/" in graph_out:
                cmd_out = run_cmd(
                    [
                        "tmux",
                        "-S",
                        sock,
                        "capture-pane",
                        "-p",
                        "-t",
                        "vhs_demo:0.2",
                    ],
                    check=False,
                ).stdout
                if ">" in cmd_out:
                    return
        time.sleep(0.05)
    raise RuntimeError(
        f"Timed out waiting for tmux panes on {sock} to become ready."
    )


def init_tmux_session(scenario: str, repo_dir: Path) -> None:
    """Create and pre-warm the 3-pane tmux session for a VHS scenario."""
    cfg = SCENARIO_CONFIGS[scenario]
    sock_path = get_tmux_socket_path(scenario)
    ready_path = get_banner_ready_path(scenario)
    if sock_path.exists():
        run_cmd(["tmux", "-S", str(sock_path), "kill-server"], check=False)
        sock_path.unlink(missing_ok=True)
    ready_path.unlink(missing_ok=True)
    Path(f"/tmp/vhs-out-{scenario}.txt").unlink(missing_ok=True)

    sock = str(sock_path)
    vhs_utils_path = PROJECT_ROOT / "media-gen" / "vhs_utils.py"
    base_path = f"{repo_dir}:{os.environ.get('PATH', '')}"

    banner_cmd = (
        f"exec {shlex.quote(PYTHON_EXE)} "
        f"{shlex.quote(str(vhs_utils_path))} banner "
        f"{shlex.quote(cfg.banner_title)} "
        f"--subtext {shlex.quote(cfg.banner_subtext)} "
        f"--comment-reader --ready-file {shlex.quote(str(ready_path))}"
    )
    graph_cmd = (
        "export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null; "
        "exec watch -c -t -n 1 "
        "'git log --graph --oneline --all --decorate --color'"
    )
    demo_export = "export GIT_SCRIPTS_DEMO=1; " if cfg.demo_env else ""
    shell_cmd = (
        "export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null "
        f"PATH={shlex.quote(base_path)} "
        'PS1="> "; '
        f"{demo_export}"
        "clear; "
        "exec bash --norc --noprofile -i"
    )

    run_cmd(
        [
            "tmux",
            "-f",
            "/dev/null",
            "-S",
            sock,
            "new-session",
            "-d",
            "-s",
            "vhs_demo",
            "-x",
            "137",
            "-y",
            "29",
            "-c",
            str(repo_dir),
            banner_cmd,
        ]
    )
    try:
        _configure_tmux_options(sock, cfg)

        run_cmd(
            [
                "tmux",
                "-S",
                sock,
                "split-window",
                "-t",
                "vhs_demo:0.0",
                "-v",
                "-l",
                "21",
                "-c",
                str(repo_dir),
                graph_cmd,
            ]
        )
        run_cmd(
            [
                "tmux",
                "-S",
                sock,
                "split-window",
                "-t",
                "vhs_demo:0.1",
                "-h",
                "-p",
                "50",
                "-c",
                str(repo_dir),
                shell_cmd,
            ]
        )
        run_cmd(["tmux", "-S", sock, "select-pane", "-t", "vhs_demo:0.0"])
        _wait_for_tmux_panes_ready(sock, ready_path)
    except Exception:
        cleanup_scenario(scenario)
        raise


def prepare_demo_environment(
    scenario: str, *, init_tmux: bool = False
) -> Path:
    """Build the demo git repository and optionally start the tmux session."""
    if scenario not in SCENARIO_CONFIGS:
        raise ValueError(f"Unknown scenario {scenario}")

    cleanup_scenario(scenario)

    os.environ["GIT_CONFIG_GLOBAL"] = "/dev/null"
    os.environ["GIT_CONFIG_SYSTEM"] = "/dev/null"

    repo_dir = Path(f"/tmp/vhs-repo-{scenario}")
    remote_dir = Path(f"/tmp/vhs-remote-{scenario}")
    remote_dir.mkdir(parents=True, exist_ok=True)
    repo_dir.mkdir(parents=True, exist_ok=True)

    run_cmd(["git", "init", "--bare", "-b", "main"], cwd=str(remote_dir))

    os.chdir(repo_dir)
    run_cmd(["git", "init", "-b", "main"])
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
    scenarios[scenario](repo_dir)
    create_wrappers(repo_dir)

    if init_tmux:
        init_tmux_session(scenario, repo_dir)

    return repo_dir


def setup_demo_repo() -> None:
    """CLI entrypoint to create and set up the fake git repo topology."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        default="rebase-prefix",
        choices=tuple(SCENARIO_CONFIGS),
        help="Scenario to setup",
    )
    parser.add_argument(
        "--init-tmux",
        action="store_true",
        help="Also initialize the isolated 3-pane tmux session.",
    )
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Attach to pre-initialized tmux session (or initialize first).",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Clean up the scenario's tmux session and temporary directories.",
    )
    args = parser.parse_args()

    if args.cleanup:
        cleanup_scenario(args.scenario)
        return

    if args.attach:
        sock_path = get_tmux_socket_path(args.scenario)
        has_session = (
            sock_path.exists()
            and run_cmd(
                [
                    "tmux",
                    "-S",
                    str(sock_path),
                    "has-session",
                    "-t",
                    "vhs_demo",
                ],
                check=False,
            ).returncode
            == 0
        )
        if not has_session:
            prepare_demo_environment(args.scenario, init_tmux=True)
        os.execvp(
            "tmux",
            ["tmux", "-S", str(sock_path), "attach-session", "-t", "vhs_demo"],
        )

    try:
        repo_dir = prepare_demo_environment(
            args.scenario, init_tmux=args.init_tmux
        )
    except ValueError as err:
        print(str(err))
        sys.exit(1)

    print(f"Repo setup complete for {args.scenario} in {repo_dir.resolve()}")


if __name__ == "__main__":
    setup_demo_repo()
