from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.cmd.rebase_orchestrator import handle_interactive_conflict
from git_scripts.models import RebaseStatus, ScriptAbortError


class TestCmdRebaseOrchestrator(absltest.TestCase):
    @patch("git_scripts.cmd.rebase_orchestrator.rebase_continue")
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

    @patch("git_scripts.cmd.rebase_orchestrator.rebase_abort")
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

    @patch("git_scripts.cmd.rebase_orchestrator.rebase_continue")
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

    @patch("git_scripts.cmd.rebase_orchestrator.rebase_abort")
    @patch("git_scripts.cmd.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_succeeds_if_continued_externally(
        self, mock_rebase_continue, mock_is_worktree_busy, mock_rebase_abort
    ):
        mock_ui = MagicMock()
        # Initial choice: resolve manually
        # Second choice inside the false worktree check: "Yes"
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

    @patch("git_scripts.cmd.rebase_orchestrator.rebase_abort")
    @patch("git_scripts.cmd.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase_orchestrator.rebase_continue")
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

    @patch("git_scripts.cmd.rebase_orchestrator.is_worktree_busy")
    @patch("git_scripts.cmd.rebase_orchestrator.rebase_continue")
    def test_handle_interactive_conflict_loops_until_conflicts_resolved(
        self, mock_rebase_continue, mock_is_worktree_busy
    ):
        mock_ui = MagicMock()
        # Loops once because still busy, then succeeds
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


if __name__ == "__main__":
    absltest.main()
