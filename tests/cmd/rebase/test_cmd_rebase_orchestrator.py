from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.cmd.rebase.rebase_orchestrator import (
    handle_interactive_conflict,
    prompt_and_delete_merged,
    rebase_loop,
    rebase_single_branch,
    resolve_conflicted_branch,
)
from git_scripts.git.core import GitExecutionError
from git_scripts.models import (
    BatchRebaseConfig,
    BranchRebasePlan,
    RebaseAction,
    RebaseStatus,
    ScriptAbortError,
    SingleBranchResult,
    WorktreeState,
)
from git_scripts.ui import UI
from tests.helpers import GitTestRepo


class TestCmdRebaseOrchestrator(absltest.TestCase):
    def test_prompt_and_delete_merged_detaches_linked_worktree_before_delete(
        self,
    ):
        repo_helper = GitTestRepo()
        self.addCleanup(repo_helper.cleanup)
        repo_helper.checkout("main")
        repo_helper.checkout("ch3/quota-service-owners", create=True)
        repo_helper.commit("quota", "quota.txt", "quota")
        repo_helper.checkout("main")

        wt_path = f"{repo_helper.temp_dir.name}/wt_quota"
        repo_helper.create_worktree(wt_path, "ch3/quota-service-owners")

        result = SingleBranchResult(
            branches_to_delete={"ch3/insrc-iii", "ch3/quota-service-owners"}
        )
        mock_ui = MagicMock()
        mock_ui.auto_yes = False
        mock_ui.pluralize.side_effect = UI(plain=True).pluralize
        mock_ui.ask_choice.return_value = "Select which to delete"
        mock_ui.ask_checkbox.return_value = ["ch3/quota-service-owners"]

        prompt_and_delete_merged(
            result,
            auto_delete=False,
            ui=mock_ui,
            repo_path=repo_helper.path,
            target="main",
        )

        self.assertNotIn(
            "ch3/quota-service-owners",
            set(repo_helper.get_pygit2_repo().branches.local),
        )
        self.assertTrue(
            any(
                "Detaching 'ch3/quota-service-owners'" in str(call.args[0])
                for call in mock_ui.print.call_args_list
                if call.args
            )
        )

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.detach_worktrees")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.pygit2.Repository")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.run_cmd")
    def test_prompt_and_delete_merged_reports_error_and_partial_deletions(
        self, mock_run_cmd, mock_repo_cls, mock_detach
    ):
        del mock_detach

        def side_effect(cmd, cwd=None):
            del cwd
            if cmd[:3] == ["git", "branch", "-D"]:
                raise GitExecutionError("checked out at worktree")
            return ""

        mock_run_cmd.side_effect = side_effect
        mock_repo_cls.return_value.branches.local = ["ch3/kept-branch"]
        result = SingleBranchResult(
            branches_to_delete={"ch3/deleted-branch", "ch3/kept-branch"}
        )
        mock_ui = MagicMock()
        mock_ui.auto_yes = True

        prompt_and_delete_merged(
            result,
            auto_delete=True,
            ui=mock_ui,
            repo_path=".",
            target="main",
        )

        printed_renderables = [
            call.args[0] for call in mock_ui.print.call_args_list if call.args
        ]
        self.assertTrue(
            any(
                "Failed to delete branches" in str(r)
                for r in printed_renderables
            )
        )
        panel_renderables = [
            getattr(r, "renderable", "")
            for r in printed_renderables
            if getattr(r, "title", None)
            == "[bold red]Deleted Branches[/bold red]"
        ]
        self.assertEqual(len(panel_renderables), 1)
        self.assertIn("ch3/deleted-branch", str(panel_renderables[0]))
        self.assertNotIn("ch3/kept-branch", str(panel_renderables[0]))

    @patch("git_scripts.git.worktrees.is_worktree_busy", return_value=True)
    def test_prompt_and_delete_merged_skips_detach_when_worktree_is_busy(
        self, mock_is_busy
    ):
        repo_helper = GitTestRepo()
        self.addCleanup(repo_helper.cleanup)
        repo_helper.checkout("main")
        repo_helper.checkout("ch3/busy-branch", create=True)
        repo_helper.commit("busy", "busy.txt", "busy")
        repo_helper.checkout("main")

        wt_path = f"{repo_helper.temp_dir.name}/wt_busy"
        repo_helper.create_worktree(wt_path, "ch3/busy-branch")

        result = SingleBranchResult(branches_to_delete={"ch3/busy-branch"})
        mock_ui = MagicMock()
        mock_ui.auto_yes = True

        prompt_and_delete_merged(
            result,
            auto_delete=True,
            ui=mock_ui,
            repo_path=repo_helper.path,
            target="main",
        )

        mock_is_busy.assert_called_once_with(wt_path)
        self.assertIn(
            "ch3/busy-branch",
            set(repo_helper.get_pygit2_repo().branches.local),
        )
        self.assertTrue(
            any(
                f"Worktree '{wt_path}' is busy" in str(call.args[0])
                for call in mock_ui.print.call_args_list
                if call.args
            )
        )

    def test_prompt_and_delete_merged_detaches_head_when_target_in_worktree(
        self,
    ):
        repo_helper = GitTestRepo()
        self.addCleanup(repo_helper.cleanup)
        repo_helper.checkout("main")
        repo_helper.checkout("ch3/merged-current", create=True)
        repo_helper.commit("merged", "merged.txt", "merged")

        wt_main = f"{repo_helper.temp_dir.name}/wt_main"
        repo_helper.create_worktree(wt_main, "main")

        result = SingleBranchResult(branches_to_delete={"ch3/merged-current"})
        mock_ui = MagicMock()
        mock_ui.auto_yes = True

        prompt_and_delete_merged(
            result,
            auto_delete=True,
            ui=mock_ui,
            repo_path=repo_helper.path,
            target="main",
        )

        repo = repo_helper.get_pygit2_repo()
        self.assertNotIn("ch3/merged-current", set(repo.branches.local))
        self.assertTrue(repo.head_is_detached)

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_raises_abort_on_exit_without_rollback(
        self, mock_rebase_continue
    ):
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Exit script without rollback"

        with self.assertRaises(ScriptAbortError):
            handle_interactive_conflict(".", mock_ui, "my-branch")

        mock_rebase_continue.assert_not_called()
        mock_ui.print.assert_any_call(
            "    [red]❌  Conflict detected on branch "
            "'[bold]my-branch[/bold]'.[/red]"
        )

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_abort")
    def test_handle_interactive_conflict_aborts_rebase_when_user_rolls_back(
        self, mock_rebase_abort
    ):
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Rollback stack and skip to next"

        status, err_msg = handle_interactive_conflict(
            ".", mock_ui, "my-branch"
        )

        self.assertEqual(status, RebaseStatus.ERROR)
        mock_rebase_abort.assert_called_once_with(".")

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_continues_after_manual_resolution(
        self, mock_rebase_continue
    ):
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Resolve manually, then continue"
        mock_rebase_continue.return_value = (RebaseStatus.SUCCESS, None)

        status, err_msg = handle_interactive_conflict(
            ".", mock_ui, "my-branch"
        )

        self.assertEqual(status, RebaseStatus.SUCCESS)
        mock_rebase_continue.assert_called_once_with(".")

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_abort")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_succeeds_if_continued_externally(
        self, mock_rebase_continue, mock_is_worktree_busy, mock_rebase_abort
    ):
        mock_ui = MagicMock()
        mock_ui.ask_choice.side_effect = [
            "Resolve manually, then continue",
            "Yes",
        ]
        mock_rebase_continue.return_value = (RebaseStatus.CONFLICT, "conflict")
        mock_is_worktree_busy.return_value = False

        status, err_msg = handle_interactive_conflict(
            ".", mock_ui, "my-branch"
        )

        self.assertEqual(status, RebaseStatus.SUCCESS)
        mock_is_worktree_busy.assert_called_once_with(".")
        mock_rebase_abort.assert_not_called()

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_abort")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_errors_if_aborted_externally(
        self, mock_rebase_continue, mock_is_worktree_busy, mock_rebase_abort
    ):
        mock_ui = MagicMock()
        mock_ui.ask_choice.side_effect = [
            "Resolve manually, then continue",
            "No (Treat as aborted)",
        ]
        mock_rebase_continue.return_value = (RebaseStatus.CONFLICT, "conflict")
        mock_is_worktree_busy.return_value = False

        status, err_msg = handle_interactive_conflict(
            ".", mock_ui, "my-branch"
        )

        self.assertEqual(status, RebaseStatus.ERROR)
        mock_rebase_abort.assert_called_once_with(".")

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_loops_until_conflicts_resolved(
        self, mock_rebase_continue, mock_is_worktree_busy
    ):
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Resolve manually, then continue"
        mock_rebase_continue.side_effect = [
            (RebaseStatus.CONFLICT, "conflict"),
            (RebaseStatus.SUCCESS, None),
        ]
        mock_is_worktree_busy.return_value = True

        status, err_msg = handle_interactive_conflict(
            ".", mock_ui, "my-branch"
        )

        self.assertEqual(status, RebaseStatus.SUCCESS)
        self.assertEqual(mock_rebase_continue.call_count, 2)

    @patch(
        "git_scripts.cmd.rebase.rebase_orchestrator.handle_interactive_conflict"
    )
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_abort")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.execute_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.create_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.get_stack_branches")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.pygit2.Repository")
    def test_rebase_single_branch_aborts_and_defers_on_conflict(
        self,
        mock_repo_cls,
        mock_get_stack_branches,
        mock_create_plan,
        mock_execute_plan,
        mock_rebase_abort,
        mock_handle_conflict,
    ):
        mock_get_stack_branches.return_value = {"feat/a"}
        mock_create_plan.return_value = BranchRebasePlan(
            branch="feat/a", action=RebaseAction.REBASE_STANDARD
        )
        mock_execute_plan.return_value = (RebaseStatus.CONFLICT, "conflict")
        config = BatchRebaseConfig(
            repo_path=".",
            prefix="feat/",
            target="main",
            all_worktrees=False,
            analyzer=MagicMock(),
            branch_pool={"feat/a"},
        )
        mock_ui = MagicMock()

        result, deferred = rebase_single_branch(
            "feat/a", config, set(), mock_ui
        )

        self.assertTrue(deferred)
        self.assertEqual(result.failed_log, [])
        self.assertEqual(result.success_log, [])
        mock_rebase_abort.assert_called_once_with(".")
        mock_handle_conflict.assert_not_called()

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.format_stack_tree")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.is_obsolete")
    @patch(
        "git_scripts.cmd.rebase.rebase_orchestrator.sync_colocated_branches"
    )
    @patch(
        "git_scripts.cmd.rebase.rebase_orchestrator.handle_interactive_conflict"
    )
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.execute_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.create_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.get_stack_branches")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.pygit2.Repository")
    def test_resolve_conflicted_branch_skips_prompt_when_sync_plan_succeeds(
        self,
        mock_repo_cls,
        mock_get_stack_branches,
        mock_create_plan,
        mock_execute_plan,
        mock_handle_conflict,
        mock_sync_colocated,
        mock_is_obsolete,
        mock_format_tree,
    ):
        del mock_sync_colocated
        mock_repo_cls.return_value.revparse_single.return_value.id = "0" * 40
        mock_get_stack_branches.return_value = {"feat/fork-b"}
        mock_create_plan.return_value = BranchRebasePlan(
            branch="feat/fork-b",
            action=RebaseAction.REBASE_ONTO_SYNC,
            sync_branch="feat/stem",
            sync_old_hash="old123",
            sync_new_hash="new456",
        )
        mock_execute_plan.return_value = (RebaseStatus.SUCCESS, None)
        mock_is_obsolete.return_value = False
        mock_format_tree.return_value = "tree-fork-b-ok"
        config = BatchRebaseConfig(
            repo_path=".",
            prefix="feat/",
            target="main",
            all_worktrees=False,
            analyzer=MagicMock(),
            branch_pool={"feat/stem", "feat/fork-b"},
        )
        mock_ui = MagicMock()

        result = resolve_conflicted_branch("feat/fork-b", config, mock_ui)

        mock_create_plan.assert_called_once_with(
            config.analyzer, "feat/fork-b"
        )
        mock_handle_conflict.assert_not_called()
        self.assertEqual(result.success_log, ["tree-fork-b-ok"])
        self.assertEqual(result.branches_to_keep, {"feat/fork-b"})
        self.assertEqual(result.failed_log, [])

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.format_stack_tree")
    @patch(
        "git_scripts.cmd.rebase.rebase_orchestrator.handle_interactive_conflict"
    )
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.execute_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.create_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.get_stack_branches")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.pygit2.Repository")
    def test_resolve_conflicted_branch_records_failure_when_conflict_aborts(
        self,
        mock_repo_cls,
        mock_get_stack_branches,
        mock_create_plan,
        mock_execute_plan,
        mock_handle_conflict,
        mock_format_tree,
    ):
        del mock_repo_cls
        mock_get_stack_branches.return_value = {"feat/conflict"}
        mock_create_plan.return_value = BranchRebasePlan(
            branch="feat/conflict", action=RebaseAction.REBASE_STANDARD
        )
        mock_execute_plan.return_value = (
            RebaseStatus.CONFLICT,
            "merge conflict",
        )
        mock_handle_conflict.return_value = (RebaseStatus.ERROR, None)
        mock_format_tree.return_value = "tree-conflict-failed"
        config = BatchRebaseConfig(
            repo_path=".",
            prefix="feat/",
            target="main",
            all_worktrees=False,
            analyzer=MagicMock(),
            branch_pool={"feat/conflict"},
        )
        mock_ui = MagicMock()

        result = resolve_conflicted_branch("feat/conflict", config, mock_ui)

        mock_handle_conflict.assert_called_once_with(
            ".", mock_ui, "feat/conflict"
        )
        self.assertEqual(result.failed_log, ["tree-conflict-failed"])
        self.assertEqual(result.success_log, [])

    @patch(
        "git_scripts.cmd.rebase.rebase_orchestrator.resolve_conflicted_branch"
    )
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_single_branch")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.manage_worktrees")
    def test_rebase_loop_propagates_abort_through_manage_worktrees(
        self,
        mock_manage_wt,
        mock_rebase_single,
        mock_resolve_conflicted,
    ):
        exit_exc_types = []

        class FakeWorktreeContext:
            def __enter__(self):
                return WorktreeState(detached_map={}, failed_branches=set())

            def __exit__(self, exc_type, exc_val, exc_tb):
                exit_exc_types.append(exc_type)
                return False

        mock_manage_wt.return_value = FakeWorktreeContext()
        mock_rebase_single.return_value = (MagicMock(), True)
        mock_resolve_conflicted.side_effect = ScriptAbortError("Aborted")

        analyzer = MagicMock()
        analyzer.tips = ["feat/a"]
        mock_ui = MagicMock()
        mock_ui.console = UI(plain=True).console

        _, completed = rebase_loop(
            analyzer=analyzer,
            repo_path=".",
            prefix="feat/",
            target="main",
            all_worktrees=True,
            ui=mock_ui,
            branch_pool={"feat/a"},
        )

        self.assertFalse(completed)
        self.assertEqual(exit_exc_types, [ScriptAbortError])

    @patch("git_scripts.cmd.rebase.rebase_orchestrator.format_stack_tree")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.rebase_abort")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.execute_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.create_rebase_plan")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.get_stack_branches")
    @patch("git_scripts.cmd.rebase.rebase_orchestrator.pygit2.Repository")
    def test_rebase_single_branch_aborts_busy_worktree_on_fatal_error(
        self,
        mock_repo_cls,
        mock_get_stack_branches,
        mock_create_plan,
        mock_execute_plan,
        mock_rebase_abort,
        mock_is_busy,
        mock_format_tree,
    ):
        mock_get_stack_branches.return_value = {"feat/a"}
        mock_create_plan.return_value = BranchRebasePlan(
            branch="feat/a", action=RebaseAction.REBASE_STANDARD
        )
        mock_execute_plan.return_value = (RebaseStatus.ERROR, "hook failed")
        mock_is_busy.return_value = True
        mock_format_tree.return_value = "feat/a"
        config = BatchRebaseConfig(
            repo_path=".",
            prefix="feat/",
            target="main",
            all_worktrees=False,
            analyzer=MagicMock(),
            branch_pool={"feat/a"},
        )

        result, deferred = rebase_single_branch(
            "feat/a", config, set(), MagicMock()
        )

        self.assertFalse(deferred)
        mock_rebase_abort.assert_called_once_with(".")
        self.assertEqual(result.failed_log, ["feat/a\n      hook failed"])


if __name__ == "__main__":
    absltest.main()
