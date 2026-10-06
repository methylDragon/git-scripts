"""Plans GitHub PR base edits and draft creations from branch topology."""

from dataclasses import dataclass

import pygit2

from git_scripts.gh.api import GitHubPr
from git_scripts.gh.template_loader import (
    compute_pr_metadata,
    get_pr_template,
    resolve_repo_workdir,
)
from git_scripts.git.topology import get_parent_branch


@dataclass(frozen=True)
class PrEditAction:
    """Action for editing an existing PR's base branch."""

    branch: str
    old_base: str
    new_base: str
    reason: str
    url: str
    pr_number: str | None = None


@dataclass
class PrCreateAction:
    """Action for creating a missing PR."""

    branch: str
    base: str
    title: str
    description: str
    url: str | None = None


def resolve_expected_pr_base(
    branch: str,
    parent_map: dict[str, str | None],
    pr_state: dict[str, GitHubPr],
    target_trunk: str,
    create_missing: bool,
) -> tuple[str, str]:
    """Resolves the target base branch and reason for an existing PR."""
    curr_ancestor = parent_map.get(branch)
    skipped = False
    while (
        not create_missing
        and curr_ancestor is not None
        and curr_ancestor not in pr_state
    ):
        curr_ancestor = parent_map.get(curr_ancestor)
        skipped = True

    expected_base = curr_ancestor if curr_ancestor else target_trunk
    reason = (
        "Matches nearest ancestor with an open PR"
        if skipped
        else "Matches local topology"
    )
    return expected_base, reason


def reconcile_edits_for_uncreated_prs(
    edits: list[PrEditAction],
    uncreated_branches: set[str],
    parent_map: dict[str, str | None],
    pr_state: dict[str, GitHubPr],
    target_trunk: str = "main",
) -> list[PrEditAction]:
    """Re-resolves PR base edits whose planned parent PR was not created."""
    if not uncreated_branches:
        return edits

    reconciled: list[PrEditAction] = []
    for edit in edits:
        if edit.new_base not in uncreated_branches:
            reconciled.append(edit)
            continue
        fallback_base, reason = resolve_expected_pr_base(
            edit.branch,
            parent_map,
            pr_state,
            target_trunk,
            create_missing=False,
        )
        if fallback_base != edit.old_base:
            reconciled.append(
                PrEditAction(
                    branch=edit.branch,
                    old_base=edit.old_base,
                    new_base=fallback_base,
                    reason=reason,
                    url=edit.url,
                    pr_number=edit.pr_number,
                )
            )
    return reconciled


def calculate_pr_actions(
    repo: pygit2.Repository,
    branches: set[str],
    pr_state: dict[str, GitHubPr],
    target_trunk: str = "main",
    create_missing: bool = False,
    parent_map: dict[str, str | None] | None = None,
    remote: str = "origin",
) -> tuple[list[PrEditAction], list[PrCreateAction]]:
    """Maps local topology to required PR base edits and draft PR creations."""
    if parent_map is None:
        parent_map = {
            b: get_parent_branch(repo, b, branches) for b in sorted(branches)
        }

    edits: list[PrEditAction] = []
    creates: list[PrCreateAction] = []

    workdir = resolve_repo_workdir(repo)
    template_refs = (
        f"refs/remotes/{remote}/{target_trunk}",
        target_trunk,
        "HEAD",
        *sorted(branches),
    )
    pr_template = get_pr_template(workdir, repo=repo, ref_names=template_refs)

    for branch in sorted(branches):
        if branch not in pr_state:
            parent = parent_map.get(branch)
            base = parent if parent else target_trunk
            title, description = compute_pr_metadata(
                repo,
                branch,
                base,
                pr_template,
                remote=remote,
            )
            creates.append(
                PrCreateAction(
                    branch=branch,
                    base=base,
                    title=title,
                    description=description,
                )
            )
            continue

        current_base = pr_state[branch].base_ref
        expected_base, reason = resolve_expected_pr_base(
            branch, parent_map, pr_state, target_trunk, create_missing
        )
        if current_base != expected_base:
            edits.append(
                PrEditAction(
                    branch=branch,
                    old_base=current_base,
                    new_base=expected_base,
                    reason=reason,
                    url=pr_state[branch].url,
                    pr_number=str(pr_state[branch].number),
                )
            )

    return edits, creates
