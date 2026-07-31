"""GitHub CLI abstractions and utilities."""

import json
import subprocess


class GhExecutionError(Exception):
    """Raised when a gh CLI command fails."""

    pass


def run_gh_cmd(cmd: list[str], cwd: str | None = None) -> str:
    """Runs a gh CLI command and returns its stdout."""
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout
    except subprocess.CalledProcessError as e:
        out = e.stdout or ""
        err = e.stderr or ""
        err_msg = out if out else err
        raise GhExecutionError(err_msg.strip()) from e


def check_gh_installed() -> bool:
    """Returns True if gh CLI is available and authenticated."""
    try:
        res = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0
    except FileNotFoundError:
        return False


def check_gh_stack_installed() -> bool:
    """Returns True if the github/gh-stack extension is installed."""
    try:
        stdout = run_gh_cmd(["gh", "extension", "list"])
        return "gh-stack" in stdout
    except GhExecutionError:
        return False


def gh_stack_link(repo_path: str, branches: list[str]) -> None:
    """Links branches into a PR stack using gh-stack."""
    if not branches:
        return

    cmd = ["gh", "stack", "link"]
    cmd.extend(branches)

    try:
        run_gh_cmd(cmd, cwd=repo_path)
    except GhExecutionError as e:
        msg = f"Failed to link stack: {str(e)}"
        raise GhExecutionError(msg) from e


def gh_stack_view(repo_path: str) -> dict:
    """Returns the JSON representation of the current stack."""
    try:
        stdout = run_gh_cmd(["gh", "stack", "view", "--json"], cwd=repo_path)
        return json.loads(stdout)
    except (GhExecutionError, json.JSONDecodeError):
        return {}


def gh_stack_checkout(repo_path: str, identifier: str) -> None:
    """Checks out a stack by its number, PR number, PR URL, or branch name."""
    try:
        run_gh_cmd(["gh", "stack", "checkout", str(identifier)], cwd=repo_path)
    except GhExecutionError as e:
        msg = f"Failed to checkout stack {identifier}: {str(e)}"
        raise GhExecutionError(msg) from e


def gh_stack_unstack(
    repo_path: str, stack_number: str | None = None, local: bool = False
) -> None:
    """Unstacks a GitHub stack using gh-stack."""
    cmd = ["gh", "stack", "unstack"]
    if stack_number is not None:
        cmd.append(str(stack_number))
    if local:
        cmd.append("--local")

    try:
        run_gh_cmd(cmd, cwd=repo_path)
    except GhExecutionError as e:
        msg = f"Failed to unstack: {str(e)}"
        raise GhExecutionError(msg) from e


def get_open_prs(repo_path: str) -> dict[str, dict[str, str]]:
    """Returns a dict mapping headRefName to baseRefName, url, and number."""
    try:
        stdout = run_gh_cmd(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "headRefName,baseRefName,url,number",
                "--limit",
                "1000",
            ],
            cwd=repo_path,
        )
        data = json.loads(stdout)
        return {
            pr["headRefName"]: {
                "base": pr["baseRefName"],
                "url": pr["url"],
                "number": str(pr["number"]),
            }
            for pr in data
        }
    except (GhExecutionError, json.JSONDecodeError):
        return {}


def gh_pr_edit(
    repo_path: str, branch: str, new_base: str, pr_number: str | None = None
) -> None:
    """Edits the base branch of an existing PR."""
    try:
        if pr_number:
            run_gh_cmd(
                [
                    "gh",
                    "api",
                    "-X",
                    "PATCH",
                    f"repos/{{owner}}/{{repo}}/pulls/{pr_number}",
                    "-f",
                    f"base={new_base}",
                ],
                cwd=repo_path,
            )
            return

        # Fallback to standard CLI if PR number is missing
        run_gh_cmd(
            ["gh", "pr", "edit", branch, "--base", new_base],
            cwd=repo_path,
        )
    except GhExecutionError as e:
        msg = f"Failed to update PR for {branch}: {str(e)}"
        raise GhExecutionError(msg) from e


def gh_pr_create(
    repo_path: str,
    branch: str,
    base: str,
    title: str | None = None,
    body: str | None = None,
    draft: bool = True,
) -> str:
    """Creates a new PR via the gh CLI and returns its URL."""
    cmd = ["gh", "pr", "create"]
    if draft:
        cmd.append("--draft")

    if title is not None:
        cmd.extend(["--title", title])
    if body is not None:
        cmd.extend(["--body", body])

    cmd.extend(["--head", branch, "--base", base])

    try:
        url = run_gh_cmd(cmd, cwd=repo_path)
        return url.strip()
    except GhExecutionError as e:
        msg = f"Failed to create PR for {branch}: {str(e)}"
        raise GhExecutionError(msg) from e
