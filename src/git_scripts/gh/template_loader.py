"""Discovers GitHub PR templates and computes commit metadata for PRs."""

import os
from collections.abc import Sequence
from pathlib import Path

import pygit2

from git_scripts.git.topology import try_revparse

_PR_TEMPLATE_DIRS = (".github", "", "docs")
_PR_TEMPLATE_NAMES = ("pull_request_template.md", "pull_request_template")


def _read_utf8_file(path: str) -> str:
    """Reads a UTF-8 file from disk, or returns an empty string on error."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _pick_subdir_template_name(names: Sequence[str]) -> str | None:
    """Picks default.md or a single .md file inside PULL_REQUEST_TEMPLATE/."""
    md_by_lower = {
        name.lower(): name for name in names if name.lower().endswith(".md")
    }
    if "default.md" in md_by_lower:
        return md_by_lower["default.md"]
    if len(md_by_lower) == 1:
        return next(iter(md_by_lower.values()))
    return None


def _find_template_in_workdir_dir(dir_path: str) -> str:
    """Searches a single directory on disk for a PR template file or subdir."""
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return ""

    files_by_lower = {
        e.lower(): e
        for e in entries
        if os.path.isfile(os.path.join(dir_path, e))
    }
    for target in _PR_TEMPLATE_NAMES:
        matched_file = files_by_lower.get(target)
        if matched_file:
            return _read_utf8_file(os.path.join(dir_path, matched_file))

    dirs_by_lower = {
        e.lower(): e
        for e in entries
        if os.path.isdir(os.path.join(dir_path, e))
    }
    subdir_name = dirs_by_lower.get("pull_request_template")
    if not subdir_name:
        return ""

    subdir_path = os.path.join(dir_path, subdir_name)
    try:
        sub_entries = [
            e
            for e in os.listdir(subdir_path)
            if os.path.isfile(os.path.join(subdir_path, e))
        ]
    except OSError:
        return ""

    chosen = _pick_subdir_template_name(sub_entries)
    return _read_utf8_file(os.path.join(subdir_path, chosen)) if chosen else ""


def _find_template_in_workdir(repo_path: str) -> str:
    """Searches GitHub PR template locations in the working tree."""
    if not repo_path or not os.path.isdir(repo_path):
        return ""
    for rel_dir in _PR_TEMPLATE_DIRS:
        dir_path = os.path.join(repo_path, rel_dir) if rel_dir else repo_path
        content = _find_template_in_workdir_dir(dir_path)
        if content:
            return content
    return ""


def _find_sub_tree_case_insensitive(
    tree: pygit2.Tree, target_name: str
) -> pygit2.Tree | None:
    """Finds a subtree inside a pygit2.Tree using case-insensitive matching."""
    target_lower = target_name.lower()
    for entry in tree:
        if (
            entry.name
            and entry.name.lower() == target_lower
            and isinstance(entry, pygit2.Tree)
        ):
            return entry
    return None


def _find_template_in_tree_dir(dir_tree: pygit2.Tree) -> str:
    """Searches a single pygit2.Tree directory for a PR template blob."""
    blobs_by_lower = {
        entry.name.lower(): entry
        for entry in dir_tree
        if entry.name and isinstance(entry, pygit2.Blob)
    }
    for target in _PR_TEMPLATE_NAMES:
        blob = blobs_by_lower.get(target)
        if blob is not None and isinstance(blob.data, bytes):
            return blob.data.decode("utf-8", errors="replace")

    sub_tree = _find_sub_tree_case_insensitive(
        dir_tree, "pull_request_template"
    )
    if sub_tree is None:
        return ""

    sub_blobs = {
        entry.name: entry
        for entry in sub_tree
        if entry.name and isinstance(entry, pygit2.Blob)
    }
    chosen = _pick_subdir_template_name(list(sub_blobs))
    if chosen and isinstance(sub_blobs[chosen].data, bytes):
        return sub_blobs[chosen].data.decode("utf-8", errors="replace")
    return ""


def _find_template_in_git_tree(
    repo: pygit2.Repository, ref_names: Sequence[str]
) -> str:
    """Searches commit trees for a PR template when missing from workdir."""
    for ref in ref_names:
        commit = try_revparse(repo, ref)
        root_tree = getattr(commit, "tree", None)
        if not isinstance(root_tree, pygit2.Tree):
            continue
        for rel_dir in _PR_TEMPLATE_DIRS:
            target_tree = (
                _find_sub_tree_case_insensitive(root_tree, rel_dir)
                if rel_dir
                else root_tree
            )
            if target_tree is None:
                continue
            content = _find_template_in_tree_dir(target_tree)
            if content:
                return content
    return ""


def resolve_repo_workdir(repo: pygit2.Repository) -> str:
    """Returns the working directory path for a repository when available."""
    workdir = getattr(repo, "workdir", None)
    if isinstance(workdir, str) and workdir:
        return workdir
    repo_path = getattr(repo, "path", "")
    if not isinstance(repo_path, str) or not repo_path:
        return ""
    path_obj = Path(repo_path.rstrip("/"))
    return str(path_obj.parent) if path_obj.name == ".git" else str(path_obj)


def get_pr_template(
    repo_path: str,
    repo: pygit2.Repository | None = None,
    ref_names: Sequence[str] = (),
) -> str:
    """Attempts to find and read a GitHub PR template from the repository."""
    content = _find_template_in_workdir(repo_path)
    if content or repo is None:
        return content
    return _find_template_in_git_tree(repo, ref_names)


def humanize_branch_name(branch: str) -> str:
    """Converts a branch name like 'feat/add-login' to 'Add login'."""
    if "/" in branch:
        branch = branch.rsplit("/", 1)[-1]

    branch = branch.replace("-", " ").replace("_", " ")
    if branch:
        branch = branch[0].upper() + branch[1:]
    return branch


def _resolve_base_commits(
    repo: pygit2.Repository,
    base: str,
    remote: str = "origin",
) -> list[pygit2.Object]:
    """Resolves commit objects to hide when walking commits ahead of base."""
    refs = (f"refs/remotes/{remote}/{base}", base)
    return [c for ref in refs if (c := try_revparse(repo, ref)) is not None]


def compute_pr_metadata(
    repo: pygit2.Repository,
    branch: str,
    base: str,
    template: str,
    remote: str = "origin",
) -> tuple[str, str]:
    """Computes the PR title and description based on commits ahead of base."""
    branch_commit = try_revparse(repo, branch)
    if branch_commit is None:
        return humanize_branch_name(branch), template

    base_commits = _resolve_base_commits(repo, base, remote=remote)
    if not base_commits:
        return humanize_branch_name(branch), template

    walker = repo.walk(branch_commit.id, pygit2.enums.SortMode.TOPOLOGICAL)
    for base_commit in base_commits:
        walker.hide(base_commit.id)

    commits = list(walker)
    if len(commits) == 1:
        commit = commits[0]
        msg = commit.message.strip()
        lines = msg.split("\n", 1)
        title = lines[0].strip()
        description = lines[1].strip() if len(lines) > 1 else ""
        if template:
            description = (
                f"{description}\n\n{template}" if description else template
            )
        return title, description
    return humanize_branch_name(branch), template
