"""Unit tests for PR action planning and uncreated-PR edit reconciliation."""

import tempfile
from unittest.mock import MagicMock, patch

import pygit2
from absl.testing import absltest

from git_scripts.gh.api import GitHubPr
from git_scripts.gh.pr_planner import (
    PrEditAction,
    calculate_pr_actions,
    reconcile_edits_for_uncreated_prs,
)
from tests.gh.test_gh_template_loader import commit_files_to_ref


class TestGhPrPlanner(absltest.TestCase):
    """Tests pure PR base edit and creation planning."""

    def test_calculate_pr_actions_repoints_child_pr_to_ancestor_pr(self):
        """Repoints a child PR to the nearest ancestor with an open PR."""
        repo = MagicMock(spec=pygit2.Repository)
        repo.workdir = "/nonexistent"
        repo.walk.return_value.__iter__.return_value = [
            MagicMock(message="Title\nDesc")
        ]
        branches = {"A", "B", "C", "D"}
        pr_state = {
            "A": GitHubPr(
                headRefName="A",
                baseRefName="main",
                url="http://github.com/A",
                number=1,
            ),
            "C": GitHubPr(
                headRefName="C",
                baseRefName="B",
                url="http://github.com/C",
                number=2,
            ),
            "D": GitHubPr(
                headRefName="D",
                baseRefName="C",
                url="http://github.com/D",
                number=3,
            ),
        }

        def fake_get_parent(_r, branch, _candidate_branches):
            return {"A": None, "B": "A", "C": "B", "D": "C"}.get(branch)

        with patch(
            "git_scripts.gh.pr_planner.get_parent_branch",
            side_effect=fake_get_parent,
        ):
            edits, creates = calculate_pr_actions(
                repo, branches, pr_state, target_trunk="main"
            )

        self.assertLen(edits, 1)
        self.assertLen(creates, 1)
        self.assertEqual(creates[0].branch, "B")
        self.assertEqual(edits[0].branch, "C")
        self.assertEqual(edits[0].old_base, "B")
        self.assertEqual(edits[0].new_base, "A")

    def test_calculate_pr_actions_aligns_forking_tree_branches_to_parent_pr(
        self,
    ):
        """Aligns forked descendant PRs to their nearest ancestor with a PR."""
        repo = MagicMock(spec=pygit2.Repository)
        repo.workdir = "/nonexistent"
        repo.walk.return_value.__iter__.return_value = [
            MagicMock(message="Title\nDesc")
        ]
        branches = {"A", "B", "C", "D", "E"}
        pr_state = {
            "A": GitHubPr(
                headRefName="A", baseRefName="main", url="urlA", number=1
            ),
            "B": GitHubPr(
                headRefName="B", baseRefName="main", url="urlB", number=2
            ),
            "D": GitHubPr(
                headRefName="D", baseRefName="main", url="urlD", number=3
            ),
            "E": GitHubPr(
                headRefName="E", baseRefName="main", url="urlE", number=4
            ),
        }

        def fake_get_parent(_r, branch, _candidate_branches):
            return {"A": None, "B": "A", "C": "A", "D": "C", "E": "A"}.get(
                branch
            )

        with patch(
            "git_scripts.gh.pr_planner.get_parent_branch",
            side_effect=fake_get_parent,
        ):
            edits, creates = calculate_pr_actions(
                repo, branches, pr_state, target_trunk="main"
            )

        self.assertLen(edits, 3)
        self.assertLen(creates, 1)
        self.assertEqual(creates[0].branch, "C")

        actions_dict = {a.branch: a.new_base for a in edits}
        self.assertEqual(actions_dict, {"B": "A", "D": "A", "E": "A"})

    def test_calculate_pr_actions_targets_new_pr_when_create_missing_set(self):
        """Points child PRs at newly created parent PRs when create_missing."""
        repo = MagicMock(spec=pygit2.Repository)
        repo.workdir = "/nonexistent"
        repo.walk.return_value.__iter__.return_value = [
            MagicMock(message="Title\nDesc")
        ]
        branches = {"A", "B", "C"}
        pr_state = {
            "A": GitHubPr(
                headRefName="A", baseRefName="main", url="urlA", number=1
            ),
            "C": GitHubPr(
                headRefName="C", baseRefName="main", url="urlC", number=2
            ),
        }

        def fake_get_parent(_r, branch, _candidate_branches):
            return {"A": None, "B": "A", "C": "B"}.get(branch)

        with patch(
            "git_scripts.gh.pr_planner.get_parent_branch",
            side_effect=fake_get_parent,
        ):
            edits, creates = calculate_pr_actions(
                repo,
                branches,
                pr_state,
                target_trunk="main",
                create_missing=True,
            )

        self.assertLen(edits, 1)
        self.assertLen(creates, 1)
        self.assertEqual(edits[0].branch, "C")
        self.assertEqual(edits[0].new_base, "B")
        self.assertEqual(creates[0].branch, "B")
        self.assertEqual(creates[0].base, "A")

    def test_calculate_pr_actions_uses_remote_trunk_when_local_trunk_is_stale(
        self,
    ):
        """Combines single-commit body and PR template even when main lags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = pygit2.init_repository(tmpdir)
            c1 = commit_files_to_ref(
                repo,
                "refs/heads/main",
                "Initial main commit",
                {".github/pull_request_template.md": "## PR Checklist"},
                parents=[],
            )
            c2 = commit_files_to_ref(
                repo,
                "refs/remotes/origin/main",
                "Upstream commit 1",
                {"a.txt": "1"},
                parents=[c1],
            )
            c3 = commit_files_to_ref(
                repo,
                "refs/remotes/origin/main",
                "Upstream commit 2",
                {"b.txt": "2"},
                parents=[c2],
            )
            commit_files_to_ref(
                repo,
                "refs/heads/feat/stack-1",
                "Add widget\n\nWhy: Needed for dashboard.",
                {"widget.py": "x = 1\n"},
                parents=[c3],
            )

            edits, creates = calculate_pr_actions(
                repo,
                {"feat/stack-1"},
                {},
                target_trunk="main",
                create_missing=True,
                parent_map={"feat/stack-1": None},
                remote="origin",
            )

            self.assertEmpty(edits)
            self.assertLen(creates, 1)
            self.assertEqual(creates[0].title, "Add widget")
            self.assertEqual(
                creates[0].description,
                "Why: Needed for dashboard.\n\n## PR Checklist",
            )

    def test_reconcile_edits_for_uncreated_prs_repoints_or_drops_edits(self):
        """Falls back to open-PR ancestor when a planned PR is skipped."""
        parent_map: dict[str, str | None] = {"A": None, "B": "A", "C": "B"}
        pr_state = {
            "A": GitHubPr(
                headRefName="A", baseRefName="main", url="urlA", number=1
            ),
            "C": GitHubPr(
                headRefName="C", baseRefName="main", url="urlC", number=2
            ),
        }
        edits = [
            PrEditAction(
                branch="C",
                old_base="main",
                new_base="B",
                reason="Matches local topology",
                url="urlC",
                pr_number="2",
            )
        ]

        reconciled = reconcile_edits_for_uncreated_prs(
            edits,
            uncreated_branches={"B"},
            parent_map=parent_map,
            pr_state=pr_state,
            target_trunk="main",
        )
        self.assertLen(reconciled, 1)
        self.assertEqual(reconciled[0].new_base, "A")
        self.assertEqual(
            reconciled[0].reason, "Matches nearest ancestor with an open PR"
        )

        # When C already targets A, the edit is dropped completely.
        edits_already_aligned = [
            PrEditAction(
                branch="C",
                old_base="A",
                new_base="B",
                reason="Matches local topology",
                url="urlC",
                pr_number="2",
            )
        ]
        self.assertEmpty(
            reconcile_edits_for_uncreated_prs(
                edits_already_aligned,
                uncreated_branches={"B"},
                parent_map=parent_map,
                pr_state=pr_state,
                target_trunk="main",
            )
        )


if __name__ == "__main__":
    absltest.main()
