"""Unit tests for git gh align command orchestration."""

from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.cmd.gh.pr_aligner import (
    _apply_pr_actions,
    _execute_creates,
    _execute_edits,
    _get_selected_branches,
    _print_branch_summary,
    _print_final_summary,
    _prompt_creates,
    _resolve_remote,
    _sync_gh_stack,
    _verify_topology,
    execute_align_pr_bases_and_sync_stacks,
)
from git_scripts.gh.api import GhExecutionError, GitHubPr
from git_scripts.gh.pr_planner import PrCreateAction, PrEditAction
from git_scripts.models import RemotePushParityResult
from git_scripts.ui import UI


class TestCmdGhAlign(absltest.TestCase):
    """Tests branch selection, topology validation, and PR alignment."""

    def test_execute_align_pr_bases_returns_false_when_gh_cli_is_not_installed(
        self,
    ):
        """Returns False when the gh CLI is unavailable."""
        with patch(
            "git_scripts.cmd.gh.pr_aligner.check_gh_installed",
            return_value=False,
        ):
            self.assertFalse(
                execute_align_pr_bases_and_sync_stacks(".", ui=MagicMock())
            )

    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_gh_installed",
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

    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_gh_installed",
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
            "git_scripts.cmd.gh.pr_aligner.find_linear_stack",
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
            "git_scripts.cmd.gh.pr_aligner.find_linear_stack",
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

    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
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
            "git_scripts.cmd.gh.pr_aligner.group_into_stacks",
            return_value={"b2": ["b1", "b2"]},
        ):
            with patch(
                "git_scripts.cmd.gh.pr_aligner.get_parent_branch",
                side_effect=lambda _r, b, _cand: (
                    "b1" if b == "b2" else ("main" if b == "b1" else None)
                ),
            ):
                with patch(
                    "git_scripts.cmd.gh.pr_aligner.check_remote_trunk_ancestry",
                    return_value=False,
                ):
                    with patch(
                        "git_scripts.cmd.gh.pr_aligner.check_gh_installed",
                        return_value=True,
                    ):
                        result = execute_align_pr_bases_and_sync_stacks(
                            ".", interactive=True, ui=ui
                        )
                        self.assertFalse(result)
                        ui.ask_checkbox.assert_called_once()
                        _, kwargs = ui.ask_checkbox.call_args
                        self.assertIn("choices", kwargs)


class TestCmdGhAlignTopologyAndStackSync(absltest.TestCase):
    """Tests topology verification, push prompts, and stack syncing."""

    @patch("git_scripts.cmd.gh.pr_aligner.push_branches")
    @patch(
        "git_scripts.cmd.gh.pr_aligner.resolve_branches_to_push",
        return_value=["b1", "b2"],
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_push_parity",
        return_value=RemotePushParityResult(unpushed_branches=("b1", "b2")),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_stack_continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_trunk_ancestry",
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
            "git_scripts.cmd.gh.pr_aligner.get_parent_branch",
            side_effect=lambda _r, b, _cand: "b1" if b == "b2" else None,
        ):
            ok, ordered, _, stacks = _verify_topology(
                repo, {"b1", "b2"}, "main", ui, repo_path="/repo"
            )

        self.assertTrue(ok)
        self.assertEqual(ordered, ["b1", "b2"])
        self.assertEqual(stacks, {"b2": ["b1", "b2"]})
        mock_resolve_push.assert_called_once()
        mock_push.assert_called_once_with(
            branches=["b1", "b2"],
            options=[],
            repo_path="/repo",
            remote="origin",
        )

    @patch("git_scripts.cmd.gh.pr_aligner.push_branches")
    @patch(
        "git_scripts.cmd.gh.pr_aligner.resolve_branches_to_push",
        return_value=["b1", "b2"],
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_push_parity",
        return_value=RemotePushParityResult(
            unpushed_branches=("b1", "b2"), diverged_branches=("b1",)
        ),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_stack_continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_trunk_ancestry",
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
            "git_scripts.cmd.gh.pr_aligner.get_parent_branch",
            side_effect=lambda _r, b, _cand: "b1" if b == "b2" else None,
        ):
            ok, ordered, _, _ = _verify_topology(
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

    @patch("git_scripts.cmd.gh.pr_aligner.push_branches")
    @patch(
        "git_scripts.cmd.gh.pr_aligner.resolve_branches_to_push",
        return_value=["b1"],
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_push_parity",
        return_value=RemotePushParityResult(unpushed_branches=("b1", "b2")),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_stack_continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_trunk_ancestry",
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
            "git_scripts.cmd.gh.pr_aligner.get_parent_branch",
            side_effect=lambda _r, b, _cand: "b1" if b == "b2" else None,
        ):
            ok, ordered, _, _ = _verify_topology(
                repo, {"b1", "b2"}, "main", ui, repo_path="/repo"
            )

        self.assertFalse(ok)
        self.assertIsNone(ordered)
        mock_push.assert_called_once_with(
            branches=["b1"], options=[], repo_path="/repo", remote="origin"
        )

    @patch("git_scripts.cmd.gh.pr_aligner.push_branches")
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_push_parity",
        return_value=RemotePushParityResult(behind_remote_branches=("b1",)),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_stack_continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_trunk_ancestry",
        return_value=True,
    )
    def test_verify_topology_aborts_when_local_branch_is_behind_remote(
        self, _mock_anc, _mock_cont, _mock_parity, mock_push
    ):
        """Fails without pushing when a local branch is behind origin."""
        repo = MagicMock()
        ui = MagicMock()

        with patch(
            "git_scripts.cmd.gh.pr_aligner.get_parent_branch",
            return_value=None,
        ):
            ok, ordered, _, _ = _verify_topology(
                repo, {"b1"}, "main", ui, repo_path="/repo"
            )

        self.assertFalse(ok)
        self.assertIsNone(ordered)
        mock_push.assert_not_called()

    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_push_parity",
        return_value=RemotePushParityResult(),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_stack_continuity",
        return_value=(True, None),
    )
    @patch(
        "git_scripts.cmd.gh.pr_aligner.check_remote_trunk_ancestry",
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
            "git_scripts.cmd.gh.pr_aligner.get_parent_branch",
            side_effect=fake_get_parent,
        ):
            ok, ordered, _, stacks = _verify_topology(
                repo, {"b1", "b2", "c1", "c2"}, "main", ui
            )

        self.assertTrue(ok)
        self.assertIsNotNone(ordered)
        self.assertEqual(stacks, {"b2": ["b1", "b2"], "c2": ["c1", "c2"]})
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
        with patch("git_scripts.cmd.gh.pr_aligner.gh_pr_edit") as mock_edit:
            self.assertTrue(_execute_edits(edits, ".", ui))
            mock_edit.assert_called_once()

        with patch(
            "git_scripts.cmd.gh.pr_aligner.gh_pr_edit",
            side_effect=GhExecutionError("err"),
        ):
            self.assertFalse(_execute_edits(edits, ".", ui))

    def test_execute_creates_invokes_gh_pr_create_for_each_missing_pr(self):
        """Calls gh_pr_create for each missing PR creation action."""
        ui = MagicMock()
        creates = [PrCreateAction("b1", "main", "T", "D")]
        with patch(
            "git_scripts.cmd.gh.pr_aligner.gh_pr_create",
            return_value="https://github.com/org/repo/pull/99",
        ) as mock_create:
            self.assertTrue(_execute_creates(creates, ".", ui))
            mock_create.assert_called_once_with(
                ".", "b1", "main", title="T", body="D"
            )
            self.assertEqual(
                creates[0].url, "https://github.com/org/repo/pull/99"
            )

    def test_apply_pr_actions_creates_before_edits_and_reconciles_skipped_pr(
        self,
    ):
        """Creates PRs before editing bases and falls back on skipped PRs."""
        ui = MagicMock()
        ui.auto_yes = True
        call_order: list[str] = []

        pr_state = {
            "A": GitHubPr(
                headRefName="A", baseRefName="main", url="url/1", number=1
            ),
            "C": GitHubPr(
                headRefName="C", baseRefName="main", url="url/3", number=3
            ),
        }
        edits = [
            PrEditAction("C", "main", "B", "Matches local topology", "url/3")
        ]
        # User deselected B in _prompt_creates (creates = []).
        with patch(
            "git_scripts.cmd.gh.pr_aligner.gh_pr_edit",
            side_effect=lambda _p, br, base, _num: call_order.append(
                f"edit:{br}->{base}"
            ),
        ):
            cancelled, ok, final_edits = _apply_pr_actions(
                edits,
                [],
                pr_state,
                ".",
                ui,
                planned_create_branches={"B"},
                parent_map={"A": None, "B": "A", "C": "B"},
                target_trunk="main",
            )

        self.assertFalse(cancelled)
        self.assertTrue(ok)
        self.assertEqual(call_order, ["edit:C->A"])
        self.assertEqual(final_edits[0].new_base, "A")

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

    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_checkout")
    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_unstack")
    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_link")
    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
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
            "git_scripts.cmd.gh.pr_aligner",
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

    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_checkout")
    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
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
            "git_scripts.cmd.gh.pr_aligner",
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

    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_link")
    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
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
            "git_scripts.cmd.gh.pr_aligner",
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

    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_unstack")
    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_link")
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

    @patch("git_scripts.cmd.gh.pr_aligner.run_cmd")
    @patch("git_scripts.cmd.gh.pr_aligner._get_checked_out_branch")
    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_checkout")
    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_unstack")
    @patch("git_scripts.cmd.gh.pr_aligner.gh_stack_link")
    def test_sync_gh_stack_restores_checked_out_branch_after_checkout(
        self,
        _mock_link,
        _mock_unstack,
        _mock_checkout,
        mock_get_branch,
        mock_run_cmd,
    ):
        """Restores original HEAD branch when gh stack checkout moves HEAD."""
        ui = MagicMock()
        ui.auto_yes = True
        mock_get_branch.side_effect = ["b2", "b1"]

        ok = _sync_gh_stack(
            "/repo",
            ["b1", "b2"],
            {
                "b1": GitHubPr(
                    headRefName="b1", baseRefName="main", url="url/1", number=1
                )
            },
            {"b1": "main", "b2": "b1"},
            "main",
            ui,
        )
        self.assertTrue(ok)
        mock_run_cmd.assert_called_once_with(
            ["git", "checkout", "b2"], cwd="/repo", check=False
        )

    @patch("git_scripts.cmd.gh.pr_aligner.get_repo")
    def test_execute_align_interactive_plans_edits_for_missing_parents(
        self,
        mock_repo,
    ):
        """Interactive mode plans child PR edits against missing parent PRs."""
        ui = MagicMock()
        ui.auto_yes = False
        ui.confirm.return_value = True
        ui.ask_choice.return_value = "Create all 1 draft PRs"
        repo = MagicMock()
        repo.references = ["refs/heads/b1", "refs/heads/b2"]
        repo.head.shorthand = "b2"
        mock_repo.return_value = repo
        mock_calc = MagicMock(
            return_value=(
                [PrEditAction("b2", "main", "b1", "reason", "url/2", "2")],
                [PrCreateAction("b1", "main", "T", "D")],
            )
        )
        with patch.multiple(
            "git_scripts.cmd.gh.pr_aligner",
            check_gh_installed=MagicMock(return_value=True),
            check_gh_stack_installed=MagicMock(return_value=False),
            check_remote_push_parity=MagicMock(
                return_value=RemotePushParityResult()
            ),
            check_stack_continuity=MagicMock(return_value=(True, "")),
            check_remote_trunk_ancestry=MagicMock(return_value=True),
            find_linear_stack=MagicMock(return_value={"b1", "b2"}),
            get_open_prs=MagicMock(
                return_value={
                    "b2": GitHubPr(
                        headRefName="b2",
                        baseRefName="main",
                        url="url/2",
                        number=2,
                    )
                }
            ),
            calculate_pr_actions=mock_calc,
            gh_pr_create=MagicMock(return_value="url/1"),
            gh_pr_edit=MagicMock(),
        ):
            self.assertTrue(execute_align_pr_bases_and_sync_stacks(".", ui=ui))
            self.assertTrue(mock_calc.call_args.kwargs["create_missing"])


if __name__ == "__main__":
    absltest.main()
