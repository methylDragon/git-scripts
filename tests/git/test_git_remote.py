from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.git.core import GitExecutionError
from git_scripts.git.remote import push_branches, update_target


class TestGitRemote(absltest.TestCase):
    @patch("git_scripts.git.remote.run_cmd")
    def test_push_branches_success(self, mock_run_cmd):
        mock_run_cmd.return_value = ""
        result = push_branches(["branch1", "branch2"], ["-f"])
        self.assertTrue(result)
        mock_run_cmd.assert_called_once_with(
            ["git", "push", "origin", "branch1", "branch2", "-f"],
            cwd=".",
            capture_output=False,
        )

    @patch("git_scripts.git.remote.run_cmd")
    def test_push_branches_failure(self, mock_run_cmd):
        mock_run_cmd.side_effect = GitExecutionError("Push failed")
        result = push_branches(["branch1"], [])
        self.assertFalse(result)

    def test_push_branches_empty(self):
        result = push_branches([], [])
        self.assertTrue(result)

    @patch("git_scripts.git.remote.is_in_another_worktree")
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_success(self, mock_run_cmd, mock_is_in_wt):
        # show-ref, show-current, checkout, rev-parse, pull
        mock_run_cmd.side_effect = ["", "other", "", "origin/main", ""]
        mock_is_in_wt.return_value = False
        ui = MagicMock()

        result = update_target(".", "main", ui)
        self.assertTrue(result)
        self.assertEqual(mock_run_cmd.call_count, 5)

    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_not_exist(self, mock_run_cmd):
        mock_run_cmd.side_effect = GitExecutionError("No such branch")
        ui = MagicMock()

        result = update_target(".", "main", ui)
        self.assertFalse(result)
        ui.print.assert_called_with(
            "❌  Error: Target branch 'main' does not exist locally."
        )


if __name__ == "__main__":
    absltest.main()
