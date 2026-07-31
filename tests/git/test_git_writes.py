import os
from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.git.writes import (
    GitExecutionError,
    manage_worktrees,
    rebase_onto,
    rebase_standard,
    run_cmd,
)
from tests.helpers import GitTestRepo


class TestGitWrites(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()
        self.repo = self.repo_helper.get_pygit2_repo()

    def tearDown(self):
        self.repo_helper.cleanup()

    def test_manage_worktrees_detaches_and_reattaches_branches(self):
        # Create a worktree for a branch
        worktree_path = os.path.join(self.repo_helper.temp_dir.name, "wt_a")
        self.repo_helper.create_worktree(worktree_path, "test-chain-a")

        # Test Context Manager
        with manage_worktrees(
            "test-chain-", active=True, repo_path=self.repo_helper.path
        ) as wt_state:
            self.assertIn(worktree_path, wt_state.detached_map)
            self.assertEqual(
                wt_state.detached_map[worktree_path], "test-chain-a"
            )
            # Ensure branch is detached
            out = run_cmd(
                ["git", "branch", "--show-current"], cwd=worktree_path
            )
            self.assertEqual(out, "")  # detached HEAD

        # Ensure branch is reattached
        out = run_cmd(["git", "branch", "--show-current"], cwd=worktree_path)
        self.assertEqual(out, "test-chain-a")

    @patch("git_scripts.git.writes.run_cmd")
    def test_rebase_onto_returns_true_when_rebase_succeeds(self, mock_run_cmd):
        mock_run_cmd.return_value = ""
        result = rebase_onto("onto_hash", "old_hash", "branch")
        self.assertTrue(result)
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.writes.run_cmd")
    def test_rebase_onto_aborts_script_without_rollback(self, mock_run_cmd):
        mock_run_cmd.side_effect = GitExecutionError("Conflict")
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort script without rollback"

        with self.assertRaises(SystemExit) as cm:
            rebase_onto("onto_hash", "old_hash", "branch", ui=mock_ui)

        self.assertEqual(cm.exception.code, 1)
        mock_ui.print.assert_any_call(
            "    [red]❌  Conflict or error.\nConflict[/red]"
        )

    @patch("git_scripts.git.writes.run_cmd")
    @patch("builtins.input")
    def test_rebase_onto_succeeds_when_user_resolves_manually(
        self, mock_input, mock_run_cmd
    ):
        mock_run_cmd.side_effect = [GitExecutionError("Conflict"), ""]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Resolve manually, then continue"
        mock_input.return_value = ""

        result = rebase_onto("onto_hash", "old_hash", "branch", ui=mock_ui)
        self.assertTrue(result)
        mock_run_cmd.assert_called_with(
            ["git", "-c", "core.editor=true", "rebase", "--continue"],
            cwd=".",
        )

    @patch("git_scripts.git.writes.run_cmd")
    @patch("builtins.input")
    def test_rebase_onto_loops_when_continue_fails_then_succeeds(
        self, mock_input, mock_run_cmd
    ):
        # 1. First call is the initial rebase_onto (fails with conflict)
        # 2. Second call is the git rebase --continue (fails with conflict)
        # 3. Third call is the git rebase --continue again (succeeds)
        mock_run_cmd.side_effect = [
            GitExecutionError("Initial Conflict"),
            GitExecutionError("Still Unresolved"),
            "",
        ]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Resolve manually, then continue"
        mock_input.return_value = ""

        result = rebase_onto("onto_hash", "old_hash", "branch", ui=mock_ui)
        self.assertTrue(result)
        self.assertEqual(mock_run_cmd.call_count, 3)
        mock_ui.print.assert_any_call(
            "    [red]⚠️  Rebase could not continue. "
            "There may still be unresolved conflicts.[/red]"
        )

    @patch("git_scripts.git.writes.run_cmd")
    def test_rebase_onto_raises_exception_when_user_aborts_and_rollbacks(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = [GitExecutionError("Conflict"), ""]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort rebase and rollback"

        with self.assertRaises(GitExecutionError):
            rebase_onto("onto_hash", "old_hash", "branch", ui=mock_ui)

        self.assertEqual(mock_run_cmd.call_count, 2)
        mock_run_cmd.assert_called_with(
            ["git", "rebase", "--abort"], cwd=".", check=False
        )

    @patch("git_scripts.git.writes.run_cmd")
    def test_rebase_standard_returns_true_when_rebase_succeeds(
        self, mock_run_cmd
    ):
        mock_run_cmd.return_value = ""
        result = rebase_standard("target", "branch")
        self.assertTrue(result)
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.writes.run_cmd")
    def test_rebase_standard_aborts_script_without_rollback(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = GitExecutionError("Conflict")
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort script without rollback"

        with self.assertRaises(SystemExit) as cm:
            rebase_standard("target", "branch", ui=mock_ui)

        self.assertEqual(cm.exception.code, 1)

    @patch("git_scripts.git.writes.run_cmd")
    def test_rebase_standard_raises_exception_when_user_aborts_and_rollbacks(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = [GitExecutionError("Conflict"), ""]
        mock_ui = MagicMock()
        mock_ui.ask_choice.return_value = "Abort rebase and rollback"

        with self.assertRaises(GitExecutionError):
            rebase_standard("target", "branch", ui=mock_ui)

        self.assertEqual(mock_run_cmd.call_count, 2)


if __name__ == "__main__":
    absltest.main()
