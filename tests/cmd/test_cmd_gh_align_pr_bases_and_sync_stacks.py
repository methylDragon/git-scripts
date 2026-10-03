"""Tests for git-gh-align-pr-bases-and-sync-stacks."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pygit2
from absl.testing import absltest

from git_scripts.cmd.gh_align_pr_bases_and_sync_stacks import (
    PrCreateAction,
    PrEditAction,
    _compute_pr_metadata,
    _execute_creates,
    _execute_edits,
    _get_pr_template,
    _get_selected_branches,
    _group_into_stacks,
    _print_branch_summary,
    _print_final_summary,
    _prompt_creates,
    _resolve_remote,
    _sync_gh_stack,
    _verify_topology,
    calculate_pr_actions,
    execute_align_pr_bases_and_sync_stacks,
)
from git_scripts.gh.api import GhExecutionError, GitHubPr
from git_scripts.models import RemotePushParityResult
from git_scripts.ui import UI


def _commit_files_to_ref(
    repo: pygit2.Repository,
    ref_name: str,
    message: str,
    files: dict[str, str],
    parents: list[pygit2.Oid],
) -> pygit2.Oid:
    """Writes nested relative file paths into a commit on ref_name."""
    sig = pygit2.Signature("Test User", "test@example.com")
    root_builder = (
        repo.TreeBuilder(repo[parents[0]].peel(pygit2.Commit).tree)
        if parents
        else repo.TreeBuilder()
    )
    subdirs: dict[str, dict[str, str]] = {}
    for path, content in files.items():
        if "/" in path:
            top, rest = path.split("/", 1)
            subdirs.setdefault(top, {})[rest] = content
        else:
            blob_oid = repo.create_blob(content.encode("utf-8"))
            root_builder.insert(path, blob_oid, pygit2.GIT_FILEMODE_BLOB)

    for top, nested_files in subdirs.items():
        sub_builder = repo.TreeBuilder()
        for sub_path, content in nested_files.items():
            blob_oid = repo.create_blob(content.encode("utf-8"))
            sub_builder.insert(sub_path, blob_oid, pygit2.GIT_FILEMODE_BLOB)
        root_builder.insert(top, sub_builder.write(), pygit2.GIT_FILEMODE_TREE)

    tree_oid = root_builder.write()
    return repo.create_commit(ref_name, sig, sig, message, tree_oid, parents)


class TestCmdGhAlignPrBasesAndSyncStacks(absltest.TestCase):
    """Unit tests for PR base alignment and branch selection."""

    def test_calculate_pr_actions_repoints_child_pr_to_ancestor_pr(
        self,
    ):
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
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
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
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
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
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
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
        self.assertEqual(creates[0].title, "Title")

    def test_get_pr_template_matches_case_insensitive_docs_and_subdir_paths(
        self,
    ):
        """Finds PR templates across mixed-case, docs/, and subdir paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gh_dir = os.path.join(tmpdir, ".github")
            os.makedirs(gh_dir)
            mixed_path = os.path.join(gh_dir, "Pull_Request_Template.md")
            with open(mixed_path, "w", encoding="utf-8") as f:
                f.write("## Mixed Case Checklist")
            self.assertEqual(
                _get_pr_template(tmpdir), "## Mixed Case Checklist"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)
            docs_tpl = os.path.join(docs_dir, "pull_request_template.md")
            with open(docs_tpl, "w", encoding="utf-8") as f:
                f.write("## Docs Template")
            self.assertEqual(_get_pr_template(tmpdir), "## Docs Template")

        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, ".github", "PULL_REQUEST_TEMPLATE")
            os.makedirs(subdir)
            single_tpl = os.path.join(subdir, "custom.md")
            with open(single_tpl, "w", encoding="utf-8") as f:
                f.write("## Single Subdir Template")
            self.assertEqual(
                _get_pr_template(tmpdir), "## Single Subdir Template"
            )

            second_tpl = os.path.join(subdir, "other.md")
            with open(second_tpl, "w", encoding="utf-8") as f:
                f.write("## Second Subdir Template")
            self.assertEqual(_get_pr_template(tmpdir), "")

            default_tpl = os.path.join(subdir, "default.md")
            with open(default_tpl, "w", encoding="utf-8") as f:
                f.write("## Subdir Default Template")
            self.assertEqual(
                _get_pr_template(tmpdir), "## Subdir Default Template"
            )

    def test_get_pr_template_reads_from_git_commit_tree_when_missing_on_disk(
        self,
    ):
        """Reads the PR template from Git commit trees when absent on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = pygit2.init_repository(tmpdir)
            _commit_files_to_ref(
                repo,
                "refs/remotes/origin/main",
                "Initial commit with template",
                {".github/PULL_REQUEST_TEMPLATE.md": "## Committed Template"},
                parents=[],
            )
            _commit_files_to_ref(
                repo,
                "refs/remotes/origin/subdir-tpl",
                "Subdir template commit",
                {"PULL_REQUEST_TEMPLATE/custom.md": "## Tree Subdir Template"},
                parents=[],
            )
            self.assertEqual(
                _get_pr_template(
                    tmpdir,
                    repo=repo,
                    ref_names=("refs/remotes/origin/main",),
                ),
                "## Committed Template",
            )
            self.assertEqual(
                _get_pr_template(
                    tmpdir,
                    repo=repo,
                    ref_names=("refs/remotes/origin/subdir-tpl",),
                ),
                "## Tree Subdir Template",
            )

    def test_calculate_pr_actions_uses_remote_trunk_when_local_trunk_is_stale(
        self,
    ):
        """Combines single-commit body and PR template even when main lags."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = pygit2.init_repository(tmpdir)
            c1 = _commit_files_to_ref(
                repo,
                "refs/heads/main",
                "Initial main commit",
                {".github/pull_request_template.md": "## PR Checklist"},
                parents=[],
            )
            c2 = _commit_files_to_ref(
                repo,
                "refs/remotes/origin/main",
                "Upstream commit 1",
                {"a.txt": "1"},
                parents=[c1],
            )
            c3 = _commit_files_to_ref(
                repo,
                "refs/remotes/origin/main",
                "Upstream commit 2",
                {"b.txt": "2"},
                parents=[c2],
            )
            _commit_files_to_ref(
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

    def test_compute_pr_metadata_resolves_remote_trunk_without_local_trunk(
        self,
    ):
        """Resolves refs/remotes/<remote>/<base> when local base is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = pygit2.init_repository(tmpdir)
            c1 = _commit_files_to_ref(
                repo,
                "refs/remotes/upstream/main",
                "Upstream base",
                {"README.md": "hi"},
                parents=[],
            )
            _commit_files_to_ref(
                repo,
                "refs/heads/feat/item",
                "Fix parser\n\nHandles empty tokens.",
                {"parser.py": "pass\n"},
                parents=[c1],
            )

            title, desc = _compute_pr_metadata(
                repo,
                "feat/item",
                "main",
                "## Template Footer",
                remote="upstream",
            )
            self.assertEqual(title, "Fix parser")
            self.assertEqual(
                desc, "Handles empty tokens.\n\n## Template Footer"
            )

    def test_execute_align_pr_bases_returns_false_when_gh_cli_is_not_installed(
        self,
    ):
        """Returns False when the gh CLI is unavailable."""
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_"
            "installed",
            return_value=False,
        ):
            self.assertFalse(
                execute_align_pr_bases_and_sync_stacks(".", ui=MagicMock())
            )

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_installed",
        return_value=True,
    )
    def test_execute_align_pr_bases_returns_true_when_no_branches_are_selected(
        self, _mock_installed, mock_repo
    ):
        """Returns True cleanly when the user cancels prefix selection."""
        repo = MagicMock()
        repo.references = ["refs/heads/feat/1"]
        repo.head.shorthand = "feat/1"
        mock_repo.return_value = repo
        ui = MagicMock()
        ui.ask_choice.return_value = "Cancel"
        self.assertTrue(
            execute_align_pr_bases_and_sync_stacks(".", prefix="feat/", ui=ui)
        )

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_installed",
        return_value=True,
    )
    def test_execute_align_pr_bases_returns_false_when_head_is_on_target(
        self, _mock_installed, mock_repo
    ):
        """Returns False when HEAD is on the target trunk branch."""
        repo = MagicMock()
        repo.references = ["refs/heads/main"]
        repo.head.shorthand = "main"
        mock_repo.return_value = repo
        self.assertFalse(
            execute_align_pr_bases_and_sync_stacks(".", ui=MagicMock())
        )

    def test_get_selected_branches_returns_stack_when_current_stack_only(self):
        """Selects the linear stack stop-bounded by target on --current."""
        repo = MagicMock()
        repo.references = ["refs/heads/prefix-1", "refs/heads/other"]
        repo.head.shorthand = "prefix-1"

        ui = UI(plain=True, auto_yes=True)
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.find_linear_"
            "stack",
            return_value={"prefix-1"},
        ) as mock_find_stack:
            res = _get_selected_branches(
                repo,
                "prefix-",
                current_stack_only=True,
                all_matching=False,
                ui=ui,
                target="main",
                interactive=False,
            )
        self.assertEqual(res, {"prefix-1"})
        mock_find_stack.assert_called_once_with(
            repo, "prefix-1", {"prefix-1"}, stop_at="main"
        )

    def test_get_selected_branches_selects_stack_when_auto_yes_and_prefix(
        self,
    ):
        """Passing -y with a prefix on a branch selects current stack."""
        repo = MagicMock()
        repo.references = [
            "refs/heads/feat/stack-1",
            "refs/heads/feat/unrelated-unpushed",
            "refs/heads/main",
        ]
        repo.head.shorthand = "feat/stack-1"

        ui = UI(plain=True, auto_yes=True)
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.find_linear_"
            "stack",
            return_value={"feat/stack-1"},
        ) as mock_find_stack:
            res = _get_selected_branches(
                repo,
                "feat/",
                current_stack_only=False,
                all_matching=False,
                ui=ui,
                target="main",
                interactive=False,
            )
        self.assertEqual(res, {"feat/stack-1"})
        mock_find_stack.assert_called_once_with(
            repo,
            "feat/stack-1",
            {"feat/stack-1", "feat/unrelated-unpushed"},
            stop_at="main",
        )

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
    def test_execute_align_pr_bases_prompts_checkbox_in_interactive_mode(
        self, mock_repo
    ):
        """Prompts for interactive stack checkbox selection."""
        ui = MagicMock()
        ui.ask_checkbox.return_value = ["b2"]
        ui.auto_yes = False

        repo = MagicMock()
        repo.references = [
            "refs/heads/b1",
            "refs/heads/b2",
            "refs/heads/main",
        ]
        mock_repo.return_value = repo
        repo.head.shorthand = "b2"

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            side_effect=lambda _r, b, _cand: (
                "b1" if b == "b2" else ("main" if b == "b1" else None)
            ),
        ):
            with patch(
                "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_"
                "remote_trunk_ancestry",
                return_value=False,
            ):
                with patch(
                    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_"
                    "gh_installed",
                    return_value=True,
                ):
                    result = execute_align_pr_bases_and_sync_stacks(
                        ".", interactive=True, ui=ui
                    )
                    self.assertFalse(result)
                    ui.ask_checkbox.assert_called_once()
                    _, kwargs = ui.ask_checkbox.call_args
                    self.assertIn("choices", kwargs)

    def test_group_into_stacks_maps_each_stack_tip_to_ordered_branch_chain(
        self,
    ):
        """Groups branches into bottom-to-top chains keyed by stack tip."""
        repo = MagicMock()

        def fake_get_parent(_r, b, _pool):
            return {"b1": "main", "b2": "b1", "c1": "main"}.get(b)

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            side_effect=fake_get_parent,
        ):
            stacks = _group_into_stacks(repo, {"b1", "b2", "c1"})
            self.assertIn("b2", stacks)
            self.assertIn("c1", stacks)
            self.assertNotIn("b1", stacks)
            self.assertEqual(stacks["b2"], ["b1", "b2"])
            self.assertEqual(stacks["c1"], ["c1"])


class TestCmdGhAlignPrBasesTopologyAndStackSync(absltest.TestCase):
    """Tests for topology verification, push prompts, and stack syncing."""

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.push_branches")
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.resolve_branches_to_"
        "push",
        return_value=["b1", "b2"],
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_"
        "parity",
        return_value=RemotePushParityResult(unpushed_branches=("b1", "b2")),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_"
        "continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_"
        "ancestry",
        return_value=True,
    )
    def test_verify_topology_prompts_and_pushes_unpushed_branches(
        self,
        _mock_anc,
        _mock_cont,
        _mock_parity,
        mock_resolve_push,
        mock_push,
    ):
        """Prompts to push unpushed stack branches and continues on push."""
        mock_push.return_value = True
        repo = MagicMock()
        ui = MagicMock()
        ui.pluralize.return_value = "2 unpushed branches"

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            side_effect=lambda _r, b, _cand: "b1" if b == "b2" else None,
        ):
            ok, ordered, _ = _verify_topology(
                repo, {"b1", "b2"}, "main", ui, repo_path="/repo"
            )

        self.assertTrue(ok)
        self.assertEqual(ordered, ["b1", "b2"])
        mock_resolve_push.assert_called_once()
        mock_push.assert_called_once_with(
            branches=["b1", "b2"],
            options=[],
            repo_path="/repo",
            remote="origin",
        )

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.push_branches")
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.resolve_branches_to_"
        "push",
        return_value=["b1", "b2"],
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_"
        "parity",
        return_value=RemotePushParityResult(
            unpushed_branches=("b1", "b2"), diverged_branches=("b1",)
        ),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_"
        "continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_"
        "ancestry",
        return_value=True,
    )
    def test_verify_topology_uses_force_with_lease_when_stack_branch_diverged(
        self,
        _mock_anc,
        _mock_cont,
        _mock_parity,
        _mock_resolve_push,
        mock_push,
    ):
        """Passes --force-with-lease when pushing rebased/diverged branches."""
        mock_push.return_value = True
        repo = MagicMock()
        ui = MagicMock()
        ui.pluralize.return_value = "2 unpushed branches"

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            side_effect=lambda _r, b, _cand: "b1" if b == "b2" else None,
        ):
            ok, ordered, _ = _verify_topology(
                repo, {"b1", "b2"}, "main", ui, repo_path="/repo"
            )

        self.assertTrue(ok)
        self.assertEqual(ordered, ["b1", "b2"])
        mock_push.assert_called_once_with(
            branches=["b1", "b2"],
            options=["--force-with-lease"],
            repo_path="/repo",
            remote="origin",
        )

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.push_branches")
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.resolve_branches_to_"
        "push",
        return_value=["b1"],
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_"
        "parity",
        return_value=RemotePushParityResult(unpushed_branches=("b1", "b2")),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_"
        "continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_"
        "ancestry",
        return_value=True,
    )
    def test_verify_topology_aborts_when_user_skips_pushing_any_stack_branch(
        self,
        _mock_anc,
        _mock_cont,
        _mock_parity,
        _mock_resolve_push,
        mock_push,
    ):
        """Aborts alignment if any stack branch stays unpushed."""
        mock_push.return_value = True
        repo = MagicMock()
        ui = MagicMock()
        ui.pluralize.return_value = "2 unpushed branches"

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            side_effect=lambda _r, b, _cand: "b1" if b == "b2" else None,
        ):
            ok, ordered, _ = _verify_topology(
                repo, {"b1", "b2"}, "main", ui, repo_path="/repo"
            )

        self.assertFalse(ok)
        self.assertIsNone(ordered)
        mock_push.assert_called_once_with(
            branches=["b1"], options=[], repo_path="/repo", remote="origin"
        )

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.push_branches")
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_"
        "parity",
        return_value=RemotePushParityResult(behind_remote_branches=("b1",)),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_"
        "continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_"
        "ancestry",
        return_value=True,
    )
    def test_verify_topology_aborts_when_local_branch_is_behind_remote(
        self, _mock_anc, _mock_cont, _mock_parity, mock_push
    ):
        """Fails without pushing when a local branch is behind origin."""
        repo = MagicMock()
        ui = MagicMock()

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            return_value=None,
        ):
            ok, ordered, _ = _verify_topology(
                repo, {"b1"}, "main", ui, repo_path="/repo"
            )

        self.assertFalse(ok)
        self.assertIsNone(ordered)
        mock_push.assert_not_called()

    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_"
        "parity",
        return_value=RemotePushParityResult(),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_"
        "continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_"
        "ancestry",
        return_value=True,
    )
    def test_verify_topology_validates_multiple_disjoint_stacks_independently(
        self, _mock_anc, mock_cont, _mock_parity
    ):
        """Checks continuity per stack instead of flattening stacks."""
        repo = MagicMock()
        ui = MagicMock()

        def fake_get_parent(_r, b, _cand):
            return {"b1": None, "b2": "b1", "c1": None, "c2": "c1"}.get(b)

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_"
            "branch",
            side_effect=fake_get_parent,
        ):
            ok, ordered, _ = _verify_topology(
                repo, {"b1", "b2", "c1", "c2"}, "main", ui
            )

        self.assertTrue(ok)
        self.assertIsNotNone(ordered)
        self.assertEqual(mock_cont.call_count, 2)
        mock_cont.assert_any_call(repo, ["b1", "b2"])
        mock_cont.assert_any_call(repo, ["c1", "c2"])

    def test_print_branch_summary_outputs_table_of_selected_branches_and_prs(
        self,
    ):
        """Renders selected branches and open PR bases in a summary panel."""
        ui = MagicMock()
        _print_branch_summary(
            {"b1", "b2"},
            {
                "b1": GitHubPr(
                    headRefName="b1", baseRefName="main", url="url", number=1
                )
            },
            ui,
        )
        ui.print.assert_called_once()
        panel = ui.print.call_args[0][0]
        self.assertIn("b1", str(panel.renderable))
        self.assertIn("b2", str(panel.renderable))

    def test_prompt_creates_returns_all_actions_when_auto_yes_is_enabled(self):
        """Returns all PR creation actions without prompting on auto_yes."""
        ui = MagicMock()
        ui.auto_yes = True
        creates = [PrCreateAction("b1", "main", "T", "D")]
        res = _prompt_creates(creates, True, ui)
        self.assertLen(res, 1)

    def test_execute_edits_updates_pr_bases_and_returns_false_on_gh_error(
        self,
    ):
        """Executes gh_pr_edit and returns False if a GitHub CLI call fails."""
        ui = MagicMock()
        edits = [PrEditAction("b1", "old", "new", "reason", "url")]
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_pr_edit"
        ) as mock_edit:
            self.assertTrue(_execute_edits(edits, ".", ui))
            mock_edit.assert_called_once()

        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_pr_edit",
            side_effect=GhExecutionError("err"),
        ):
            self.assertFalse(_execute_edits(edits, ".", ui))

    def test_execute_creates_invokes_gh_pr_create_for_each_missing_pr(self):
        """Calls gh_pr_create for each missing PR creation action."""
        ui = MagicMock()
        creates = [PrCreateAction("b1", "main", "T", "D")]
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_pr_create"
        ) as mock_create:
            self.assertTrue(_execute_creates(creates, ".", ui))
            mock_create.assert_called_once()

    def test_print_final_summary_displays_edited_created_and_skipped_prs(self):
        """Renders edited, created, and skipped PRs in the final summary."""
        ui = MagicMock()
        edits = [PrEditAction("b1", "old", "new", "reason", "url")]
        creates = [PrCreateAction("b1", "main", "T", "D")]
        pr_state = {
            "skipped": GitHubPr(
                headRefName="skipped", baseRefName="main", url="url", number=1
            )
        }
        _print_final_summary(
            edits, creates, {"skipped"}, pr_state, ui, stack_branches=["b1"]
        )
        ui.print.assert_called_once()
        panel = ui.print.call_args[0][0]
        self.assertIn("b1", str(panel.renderable))
        self.assertIn("skipped", str(panel.renderable))

    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_checkout"
    )
    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_unstack"
    )
    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_link")
    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
    def test_execute_align_pr_bases_links_stack_after_aligning_prs(
        self,
        mock_repo,
        mock_link,
        mock_unstack,
        mock_checkout,
    ):
        """Creates missing PRs and links stack branches via gh stack link."""
        ui = MagicMock()
        ui.auto_yes = True
        repo = MagicMock()
        repo.references = ["refs/heads/b1", "refs/heads/b2"]
        repo.head.shorthand = "b2"
        r1, r2 = MagicMock(), MagicMock()
        r1.name = "origin"
        r2.name = "upstream"
        repo.remotes = [r1, r2]
        mock_repo.return_value = repo
        creates = [
            PrCreateAction("b2", "b1", "T", "D"),
        ]
        mock_parity = MagicMock(return_value=RemotePushParityResult())
        mock_ancestry = MagicMock(return_value=True)
        with patch.multiple(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks",
            check_gh_installed=MagicMock(return_value=True),
            check_gh_stack_installed=MagicMock(return_value=True),
            check_remote_push_parity=mock_parity,
            check_stack_continuity=MagicMock(return_value=(True, "")),
            check_remote_trunk_ancestry=mock_ancestry,
            find_linear_stack=MagicMock(return_value={"b1", "b2"}),
            get_open_prs=MagicMock(
                return_value={
                    "b1": GitHubPr(
                        headRefName="b1",
                        baseRefName="main",
                        url="url/1",
                        number=1,
                    )
                }
            ),
            calculate_pr_actions=MagicMock(return_value=([], creates)),
            gh_pr_create=MagicMock(return_value="url/2"),
            get_parent_branch=MagicMock(
                side_effect=lambda _r, b, _c: {"b1": "main", "b2": "b1"}.get(b)
            ),
        ):
            self.assertTrue(
                execute_align_pr_bases_and_sync_stacks(
                    ".", ui=ui, create_missing=True, remote="upstream"
                )
            )
            mock_ancestry.assert_called_once_with(
                repo, "b1", "main", remote="upstream"
            )
            mock_parity.assert_called_once_with(
                repo, ["b1", "b2"], remote="upstream"
            )
            mock_checkout.assert_called_once_with(".", "1")
            mock_unstack.assert_called_once_with(".")
            mock_link.assert_called_once_with(
                ".", ["b1", "b2"], remote="upstream"
            )

    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_checkout"
    )
    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
    def test_execute_align_pr_bases_returns_false_when_gh_stack_link_fails(
        self,
        mock_repo,
        mock_checkout,
    ):
        """Returns False when gh stack link raises GhExecutionError."""
        ui = MagicMock()
        ui.auto_yes = True
        repo = MagicMock()
        repo.references = ["refs/heads/b1", "refs/heads/b2"]
        repo.head.shorthand = "b2"
        mock_repo.return_value = repo
        creates = [
            PrCreateAction("b2", "b1", "T", "D"),
        ]
        with patch.multiple(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks",
            check_gh_installed=MagicMock(return_value=True),
            check_gh_stack_installed=MagicMock(return_value=True),
            check_remote_push_parity=MagicMock(
                return_value=RemotePushParityResult()
            ),
            check_stack_continuity=MagicMock(return_value=(True, "")),
            check_remote_trunk_ancestry=MagicMock(return_value=True),
            find_linear_stack=MagicMock(return_value={"b1", "b2"}),
            get_open_prs=MagicMock(
                return_value={
                    "b1": GitHubPr(
                        headRefName="b1",
                        baseRefName="main",
                        url="url/1",
                        number=1,
                    )
                }
            ),
            calculate_pr_actions=MagicMock(return_value=([], creates)),
            gh_pr_create=MagicMock(return_value="url/2"),
            get_parent_branch=MagicMock(
                side_effect=lambda _r, b, _c: {"b1": "main", "b2": "b1"}.get(b)
            ),
            gh_stack_unstack=MagicMock(),
            gh_stack_link=MagicMock(side_effect=GhExecutionError("err")),
        ):
            self.assertFalse(
                execute_align_pr_bases_and_sync_stacks(
                    ".", ui=ui, create_missing=True
                )
            )
            mock_checkout.assert_called_once_with(".", "1")

    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_link")
    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
    def test_execute_align_pr_bases_skips_linking_without_gh_stack(
        self,
        mock_repo,
        mock_link,
    ):
        """Skips gh stack link when the gh-stack extension is not installed."""
        ui = MagicMock()
        ui.auto_yes = True
        repo = MagicMock()
        repo.references = ["refs/heads/b1", "refs/heads/b2"]
        repo.head.shorthand = "b2"
        mock_repo.return_value = repo
        creates = [
            PrCreateAction("b1", "main", "T", "D"),
            PrCreateAction("b2", "b1", "T", "D"),
        ]
        with patch.multiple(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks",
            check_gh_installed=MagicMock(return_value=True),
            check_gh_stack_installed=MagicMock(return_value=False),
            check_remote_push_parity=MagicMock(
                return_value=RemotePushParityResult()
            ),
            check_stack_continuity=MagicMock(return_value=(True, "")),
            check_remote_trunk_ancestry=MagicMock(return_value=True),
            find_linear_stack=MagicMock(return_value={"b1", "b2"}),
            get_open_prs=MagicMock(return_value={}),
            calculate_pr_actions=MagicMock(return_value=([], creates)),
            gh_pr_create=MagicMock(return_value="url/1"),
        ):
            with patch("time.sleep"):
                self.assertTrue(
                    execute_align_pr_bases_and_sync_stacks(
                        ".", ui=ui, create_missing=True
                    )
                )
                mock_link.assert_not_called()

    def test_resolve_remote_single_remote_auto_selected(self):
        """Auto-selects the single configured remote without prompting."""
        ui = MagicMock()
        repo = MagicMock()
        rem = MagicMock()
        rem.name = "origin"
        repo.remotes = [rem]
        self.assertEqual(_resolve_remote(repo, None, ui), (True, "origin"))
        ui.ask_choice.assert_not_called()

    def test_resolve_remote_multiple_remotes_prompts_with_push_default(self):
        """Prompts with ask_choice defaulting to remote.pushDefault."""
        ui = MagicMock()
        ui.ask_choice.return_value = "upstream"
        repo = MagicMock()
        r1, r2 = MagicMock(), MagicMock()
        r1.name = "origin"
        r2.name = "upstream"
        repo.remotes = [r1, r2]
        repo.config = {"remote.pushDefault": "upstream"}

        self.assertEqual(_resolve_remote(repo, None, ui), (True, "upstream"))
        ui.ask_choice.assert_called_once_with(
            "Multiple remotes detected. Which remote do you want to align to?",
            choices=["origin", "upstream"],
            default="upstream",
        )

    def test_resolve_remote_multiple_remotes_defaults_to_origin(self):
        """Defaults to origin when pushDefault is unset and origin exists."""
        ui = MagicMock()
        ui.ask_choice.return_value = "origin"
        repo = MagicMock()
        r1, r2 = MagicMock(), MagicMock()
        r1.name = "fork"
        r2.name = "origin"
        repo.remotes = [r1, r2]
        repo.config = {}

        self.assertEqual(_resolve_remote(repo, None, ui), (True, "origin"))
        ui.ask_choice.assert_called_once_with(
            "Multiple remotes detected. Which remote do you want to align to?",
            choices=["fork", "origin"],
            default="origin",
        )

    def test_resolve_remote_multiple_remotes_cancel_returns_true_none(self):
        """Returns (True, None) when the user cancels the remote prompt."""
        ui = MagicMock()
        ui.ask_choice.return_value = None
        repo = MagicMock()
        r1, r2 = MagicMock(), MagicMock()
        r1.name = "fork"
        r2.name = "upstream"
        repo.remotes = [r1, r2]
        repo.config = {}

        self.assertEqual(_resolve_remote(repo, None, ui), (True, None))
        ui.ask_choice.assert_called_once_with(
            "Multiple remotes detected. Which remote do you want to align to?",
            choices=["fork", "upstream"],
            default="fork",
        )

    def test_resolve_remote_invalid_explicit_remote_returns_false_none(self):
        """Rejects an explicit --remote that is not configured on the repo."""
        ui = MagicMock()
        repo = MagicMock()
        rem = MagicMock()
        rem.name = "origin"
        repo.remotes = [rem]

        self.assertEqual(_resolve_remote(repo, "origin", ui), (True, "origin"))
        self.assertEqual(_resolve_remote(repo, "missing", ui), (False, None))

    @patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_unstack"
    )
    @patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_link")
    def test_sync_gh_stack_deduplicates_failed_to_link_stack_prefix(
        self, mock_link, _mock_unstack
    ):
        """Strips duplicate 'Failed to link stack: ' prefix on link failure."""
        ui = MagicMock()
        ui.auto_yes = True
        mock_link.side_effect = GhExecutionError(
            "Failed to link stack: multiple remotes configured"
        )

        ok = _sync_gh_stack(
            ".",
            ["b1", "b2"],
            {},
            {"b1": "main", "b2": "b1"},
            "main",
            ui,
            remote="upstream",
        )
        self.assertFalse(ok)
        mock_link.assert_called_once_with(".", ["b1", "b2"], remote="upstream")
        printed = "\n".join(
            str(call.args[0]) for call in ui.print.call_args_list if call.args
        )
        self.assertIn(
            "Failed to link stack: [dim]multiple remotes configured[/dim]",
            printed,
        )
        self.assertNotIn(
            "Failed to link stack: Failed to link stack:", printed
        )


if __name__ == "__main__":
    absltest.main()
