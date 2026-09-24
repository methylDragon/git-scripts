from unittest.mock import patch

from absl.testing import absltest

from git_scripts.git.core import GitExecutionError
from git_scripts.git.rebase import (
    rebase_abort,
    rebase_continue,
    rebase_stack,
    rebase_stack_onto,
)
from git_scripts.models import RebaseStatus
from tests.helpers import GitTestRepo


class TestGitRebase(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()
        self.repo = self.repo_helper.get_pygit2_repo()

    def tearDown(self):
        self.repo_helper.cleanup()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_continue_returns_success_when_git_rebase_completes(
        self, mock_run_cmd
    ):
        mock_run_cmd.return_value = ""
        result = rebase_continue(".")
        self.assertEqual(result, (RebaseStatus.SUCCESS, None))

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_continue_returns_conflict_status_when_git_raises_error(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = GitExecutionError("conflict")
        result = rebase_continue(".")
        self.assertEqual(result, (RebaseStatus.CONFLICT, "conflict"))

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_abort_invokes_git_rebase_abort(self, mock_run_cmd):
        rebase_abort(".")
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_returns_success_when_onto_rebase_completes(
        self, mock_run_cmd
    ):
        mock_run_cmd.return_value = ""
        result = rebase_stack_onto("onto_hash", "old_hash", "branch")
        self.assertEqual(result, (RebaseStatus.SUCCESS, None))
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_onto_returns_conflict_status_when_conflict_occurs(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = GitExecutionError("Conflict during rebase")
        result = rebase_stack_onto("onto_hash", "old_hash", "branch")
        self.assertEqual(
            result, (RebaseStatus.CONFLICT, "Conflict during rebase")
        )

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_returns_success_when_branch_rebases_cleanly(
        self, mock_run_cmd
    ):
        mock_run_cmd.return_value = ""
        result = rebase_stack("target", "branch")
        self.assertEqual(result, (RebaseStatus.SUCCESS, None))
        mock_run_cmd.assert_called_once()

    @patch("git_scripts.git.rebase.run_cmd")
    def test_rebase_stack_returns_error_status_on_unexpected_git_failure(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = GitExecutionError("Random git error")
        result = rebase_stack("target", "branch")
        self.assertEqual(result, (RebaseStatus.ERROR, "Random git error"))


if __name__ == "__main__":
    absltest.main()
