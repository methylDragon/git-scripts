import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import filelock
import pygit2


def run_git(
    cmd: list[str], cwd: str, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a git command in the test repository."""
    return subprocess.run(
        ["git"] + cmd, cwd=cwd, check=check, capture_output=True, text=True
    )


class GitTestRepo:
    _TEMPLATE_DIR_PATH = None

    @classmethod
    def _create_template(cls):
        """
        Creates a master template repo with complex branches.
        Initializes a deeply nested, multi-forking topological branch stack.
        Essential for validating recursive and cross-stack algorithms.

        Stack Layout:
        main
        ├── test-chain-a
        │   └── test-chain-a-b
        │       └── test-chain-a-b-c (tip)
        └── test-chain-d
            └── test-chain-d-e
                └── test-chain-d-e-f
                    ├── test-chain-d-e-f-g
                    │   └── test-chain-d-e-f-g-h
                    │       └── test-chain-d-e-f-g-h-i (tip)
                    └── test-chain-d-e-f-j
                        └── test-chain-d-e-f-j-k
                            └── test-chain-d-e-f-j-k-l (tip)
        """
        # We use a chained bash script.
        # Why? pygit2 commits have different metadata.
        # We need 100% CLI parity for patch-ID.
        # Chaining prevents python subprocess overhead.
        script = """
set -e
git init --ref-format=files >/dev/null 2>&1
git config user.name "Test User"
git config user.email "test@example.com"
git commit --allow-empty -m "Initial commit" >/dev/null 2>&1
git branch -m main

commit() {
    msg=$1
    echo "$msg" > "$msg.txt"
    git add "$msg.txt"
    git commit -m "$msg" >/dev/null 2>&1
}

checkout() {
    branch=$1
    create=$2
    if [ "$create" = "True" ]; then
        git checkout -b "$branch" >/dev/null 2>&1
    else
        git checkout "$branch" >/dev/null 2>&1
    fi
}

checkout main False
commit "main-base"

# Chain A
checkout test-chain-a True
commit "a"
checkout test-chain-a-b True
commit "b"
checkout test-chain-a-b-c True
commit "c"

# Chain D
checkout main False
checkout test-chain-d True
commit "d"
checkout test-chain-d-e True
commit "e"
checkout test-chain-d-e-f True
commit "f"

# Fork G
checkout test-chain-d-e-f-g True
commit "g"
checkout test-chain-d-e-f-g-h True
commit "h"
checkout test-chain-d-e-f-g-h-i True
commit "i"

# Fork J
checkout test-chain-d-e-f False
checkout test-chain-d-e-f-j True
commit "j"
checkout test-chain-d-e-f-j-k True
commit "k"
checkout test-chain-d-e-f-j-k-l True
commit "l"

checkout main False
"""

        script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()[:12]
        base_dir = (
            pathlib.Path(tempfile.gettempdir())
            / f"git-scripts-test-template-{script_hash}"
        )
        lock_path = str(base_dir) + ".lock"
        ready_file = base_dir / ".ready"

        with filelock.FileLock(lock_path):
            if base_dir.exists():
                if ready_file.exists():
                    cls._TEMPLATE_DIR_PATH = str(base_dir)
                    return
                else:
                    # Incomplete cache from a previous killed run. Wipe it.
                    shutil.rmtree(base_dir)

            base_dir.mkdir(parents=True)
            path = str(base_dir)

            subprocess.run(["bash", "-c", script], cwd=path, check=True)
            ready_file.touch()
            cls._TEMPLATE_DIR_PATH = path

    def __init__(self, use_template: bool = True):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = self.temp_dir.name

        if use_template:
            if getattr(GitTestRepo, "_TEMPLATE_DIR_PATH", None) is None:
                GitTestRepo._create_template()
            # Clean empty dir and copy from template
            os.rmdir(self.path)
            shutil.copytree(str(GitTestRepo._TEMPLATE_DIR_PATH), self.path)
        else:
            self._init_repo()

    def cleanup(self):
        self.temp_dir.cleanup()

    def _init_repo(self):
        script = """
set -e
git init --ref-format=files >/dev/null 2>&1
git config user.name "Test User"
git config user.email "test@example.com"
git commit --allow-empty -m "Initial commit" >/dev/null 2>&1
git branch -m main
"""
        subprocess.run(["bash", "-c", script], cwd=self.path, check=True)

    def commit(
        self,
        message: str,
        file_name: str | None = None,
        file_content: str | None = None,
    ):
        """Create a commit, optionally modifying a file."""
        if file_name and file_content is not None:
            file_path = os.path.join(self.path, file_name)
            with open(file_path, "w") as f:
                f.write(file_content)
            run_git(["add", file_name], cwd=self.path)
        run_git(["commit", "--allow-empty", "-m", message], cwd=self.path)

    def checkout(
        self, branch: str, create: bool = False, detach: bool = False
    ):
        cmd = ["checkout"]
        if create:
            cmd.extend(["-b", branch])
        else:
            cmd.append(branch)

        if detach:
            cmd.append("--detach")

        run_git(cmd, cwd=self.path)

    def merge(self, branch: str, fast_forward: bool = True):
        cmd = ["merge", branch]
        if not fast_forward:
            cmd.append("--no-ff")
        run_git(cmd, cwd=self.path)

    def create_worktree(
        self,
        path: str,
        branch: str,
        create_branch: bool = False,
    ):
        cmd = ["worktree", "add"]
        if create_branch:
            cmd.extend(["-b", branch, path])
        else:
            cmd.extend([path, branch])
        run_git(cmd, cwd=self.path)

    def tag(
        self, tag_name: str, ref: str | None = None, force: bool = False
    ) -> None:
        cmd = ["tag"]
        if force:
            cmd.append("-f")
        cmd.append(tag_name)
        if ref:
            cmd.append(ref)
        run_git(cmd, cwd=self.path)

    def add_remote(self, name: str, url: str) -> None:
        run_git(["remote", "add", name, url], cwd=self.path)

    def rev_parse(self, rev: str) -> str:
        res = run_git(["rev-parse", rev], cwd=self.path)
        return res.stdout.strip()

    def get_pygit2_repo(self) -> pygit2.Repository:
        return pygit2.Repository(self.path)


def setup_multi_worktree_gk_repo(
    repo_helper: GitTestRepo, base_dir: pathlib.Path
) -> tuple[pathlib.Path, pathlib.Path]:
    """Populates a GitTestRepo with CI tags, bazel symlinks, and a worktree."""
    main_repo = pathlib.Path(repo_helper.path)
    repo_helper.add_remote("origin", "https://example.com/repo.git")
    repo_helper.commit("add gitignore", ".gitignore", "bazel-*\n")

    for vtag in ("v1.0.0", "v2.0.0", "internal-milestone-1"):
        repo_helper.tag(vtag)

    for i in range(1, 16):
        repo_helper.tag(f"candidate/2026-01-{i:02d}")
    for i in range(1, 13):
        repo_helper.tag(f"release/2026.{i:02d}")

    fake_bazel_cache = base_dir / "bazel_cache_execroot"
    fake_bazel_cache.mkdir(parents=True, exist_ok=True)
    (main_repo / "bazel-out").symlink_to(fake_bazel_cache)

    wt_repo = base_dir / "repo-wt-1"
    repo_helper.create_worktree(str(wt_repo), "feat/wt1", create_branch=True)
    (wt_repo / "bazel-out").symlink_to(fake_bazel_cache)
    return main_repo, wt_repo


def create_fake_gitkraken_home(
    base_dir: pathlib.Path,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Creates a mock ~/.gitkraken profile and bloated repoSettings file."""
    home_dir = base_dir / "home"
    gk_root = home_dir / ".gitkraken"
    profile_dir = gk_root / "profiles" / "d6e5a8ca26e14325a4275fc33b17e16f"
    rs_dir = profile_dir / "repoSettings"
    rs_dir.mkdir(parents=True, exist_ok=True)

    profile_file = profile_dir / "profile"
    profile_data = {
        "selectedGitPath": "/usr/bin/git",
        "repoInitDetails": {
            "openTab1": {"repoPath": "/keep/open/tab/1"},
            "openTab2": {"repoPath": "/keep/open/tab/2"},
        },
    }
    profile_file.write_text(json.dumps(profile_data), encoding="utf-8")

    rs_file = rs_dir / "insrc-mock.json"
    vis = {"visible": True}
    tags_map = {f"candidate/2026-01-{i:02d}": vis for i in range(1, 16)}
    tags_map["v1.0.0"] = {"visible": True}
    rs_file.write_text(json.dumps({"tags": tags_map}), encoding="utf-8")
    return home_dir, profile_file, rs_file
