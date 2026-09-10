from unittest.mock import patch

from absl.testing import absltest

from git_scripts.git.core import GitExecutionError
from git_scripts.git.remote import push_branches, update_target
from git_scripts.models import UpdateTargetResult


class TestGitRemote(absltest.TestCase):
    @patch("git_scripts.git.remote.run_cmd")
    def test_push_branches_success(self, mock_run_cmd):
        push_branches(["branch1", "branch2"], ["--force"], ".")
        mock_run_cmd.assert_called_once_with(
            ["git", "push", "origin", "branch1", "branch2", "--force"],
            cwd=".",
            capture_output=False,
        )

    @patch("git_scripts.git.remote.run_cmd")
    def test_push_branches_empty(self, mock_run_cmd):
        push_branches([], ["--force"], ".")
        mock_run_cmd.assert_not_called()

    @patch("git_scripts.git.remote.is_in_another_worktree")
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_success(self, mock_run_cmd, mock_is_in_wt):
        # show-ref, show-current, checkout, rev-parse, pull
        mock_run_cmd.side_effect = ["", "other", "", "origin/main", ""]
        mock_is_in_wt.return_value = False

        result = update_target(".", "main")
        self.assertEqual(result, UpdateTargetResult.SUCCESS)
        self.assertEqual(mock_run_cmd.call_count, 5)

    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_not_exist(self, mock_run_cmd):
        mock_run_cmd.side_effect = GitExecutionError("No such branch")

        with self.assertRaisesRegex(
            GitExecutionError, "Target branch 'main' does not exist locally."
        ):
            update_target(".", "main")


if __name__ == "__main__":
    absltest.main()
