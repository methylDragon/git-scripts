from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.git.core import GitExecutionError
from git_scripts.git.rebase import rebase_stack, rebase_stack_onto
from tests.helpers import GitTestRepo


class TestGitRebase(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()
        self.repo = self.repo_helper.get_pygit2_repo()

    def tearDown(self):
        self.repo_helper.cleanup()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_returns_true_when_rebase_succeeds(
        self, mock_run_cmd
    ):
        mock_run_cmd.return_value = ""
        result = rebase_stack_onto("onto_hash", "old_hash", "branch")
        self.assertTrue(result)
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_aborts_script_without_rollback(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = GitExecutionError("Conflict")
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort script without rollback"

        with self.assertRaises(SystemExit) as cm:
            rebase_stack_onto("onto_hash", "old_hash", "branch", ui=mock_ui)

        self.assertEqual(cm.exception.code, 1)
        mock_ui.print.assert_any_call(
            "    [red]❌  Conflict or error on branch '[bold]branch[/bold]'.\n"
            "Conflict[/red]"
        )

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_succeeds_when_user_resolves_manually(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = [GitExecutionError("Conflict"), ""]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Resolve manually, then continue"

        result = rebase_stack_onto(
            "onto_hash", "old_hash", "branch", ui=mock_ui
        )
        self.assertTrue(result)
        mock_run_cmd.assert_called_with(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd=".",
            capture_output=False,
        )

    @patch("git_scripts.git.rebase.is_worktree_busy")
    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_loops_when_continue_fails_then_succeeds(
        self, mock_run_cmd, mock_is_worktree_busy
    ):
        # 1. First call is the initial rebase_stack_onto (fails with conflict)
        # 2. Second call is the git rebase --continue (fails with conflict)
        # 3. Third call is the git rebase --continue again (succeeds)
        mock_run_cmd.side_effect = [
            GitExecutionError("Initial Conflict"),
            GitExecutionError("Still Unresolved"),
            "",
        ]
        mock_is_worktree_busy.return_value = True
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Resolve manually, then continue"

        result = rebase_stack_onto(
            "onto_hash", "old_hash", "branch", ui=mock_ui
        )
        self.assertTrue(result)
        self.assertEqual(mock_run_cmd.call_count, 3)

    @patch("git_scripts.git.rebase.is_worktree_busy")
    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_handles_accidentally_continued_rebase(
        self, mock_run_cmd, mock_is_worktree_busy
    ):
        mock_run_cmd.side_effect = [
            GitExecutionError("Initial Conflict"),
            GitExecutionError("fatal: No rebase in progress?"),
        ]
        mock_is_worktree_busy.return_value = False

        mock_ui = MagicMock()
        mock_ui.ask_choice.side_effect = [
            "Resolve manually, then continue",
            "Yes",
        ]

        result = rebase_stack_onto(
            "onto_hash", "old_hash", "branch", ui=mock_ui
        )
        self.assertTrue(result)
        self.assertEqual(mock_run_cmd.call_count, 2)
        mock_is_worktree_busy.assert_called_once()
        mock_ui.print.assert_any_call(
            "    ✅  Rebase assumed finished. Continuing script..."
        )

    @patch("git_scripts.git.rebase.is_worktree_busy")
    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_handles_accidentally_aborted_rebase(
        self, mock_run_cmd, mock_is_worktree_busy
    ):
        mock_run_cmd.side_effect = [
            GitExecutionError("Initial Conflict"),
            GitExecutionError("fatal: No rebase in progress?"),
            "",
        ]
        mock_is_worktree_busy.return_value = False

        mock_ui = MagicMock()
        mock_ui.ask_choice.side_effect = [
            "Resolve manually, then continue",
            "No (Treat as aborted)",
        ]

        with self.assertRaises(GitExecutionError):
            rebase_stack_onto("onto_hash", "old_hash", "branch", ui=mock_ui)

        self.assertEqual(mock_run_cmd.call_count, 3)

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_raises_exception_when_user_aborts_and_rollbacks(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = [GitExecutionError("Conflict"), ""]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort rebase and rollback"

        with self.assertRaises(GitExecutionError):
            rebase_stack_onto("onto_hash", "old_hash", "branch", ui=mock_ui)

        self.assertEqual(mock_run_cmd.call_count, 2)
        mock_run_cmd.assert_called_with(
            ["git", "rebase", "--abort"], cwd=".", check=False
        )

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_returns_true_when_rebase_succeeds(
        self, mock_run_cmd
    ):
        mock_run_cmd.return_value = ""
        result = rebase_stack("target", "branch")
        self.assertTrue(result)
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_aborts_script_without_rollback(self, mock_run_cmd):
        mock_run_cmd.side_effect = GitExecutionError("Conflict")
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort script without rollback"

        with self.assertRaises(SystemExit) as cm:
            rebase_stack("target", "branch", ui=mock_ui)

        self.assertEqual(cm.exception.code, 1)

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_raises_exception_when_user_aborts_and_rollbacks(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = [GitExecutionError("Conflict"), ""]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort rebase and rollback"

        with self.assertRaises(GitExecutionError):
            rebase_stack("target", "branch", ui=mock_ui)

        self.assertEqual(mock_run_cmd.call_count, 2)


if __name__ == "__main__":
    absltest.main()
