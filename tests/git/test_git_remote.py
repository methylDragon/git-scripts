from unittest.mock import patch

from absl.testing import absltest

from git_scripts.git.core import GitExecutionError
from git_scripts.git.remote import push_branches, update_target
from git_scripts.models import UpdateTargetResult


class TestGitRemote(absltest.TestCase):
    @patch("git_scripts.git.remote.run_cmd")
    def test_push_branches_invokes_git_push_with_branches_and_options(
        self, mock_run_cmd
    ):
        push_branches(["branch1", "branch2"], ["--force"], ".")
        mock_run_cmd.assert_called_once_with(
            ["git", "push", "origin", "branch1", "branch2", "--force"],
            cwd=".",
            capture_output=False,
        )

    @patch("git_scripts.git.remote.run_cmd")
    def test_push_branches_skips_git_push_when_branch_list_is_empty(
        self, mock_run_cmd
    ):
        push_branches([], ["--force"], ".")
        mock_run_cmd.assert_not_called()

    @patch("git_scripts.git.remote.is_in_another_worktree")
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_pulls_latest_changes_and_restores_original_branch(
        self, mock_run_cmd, mock_is_in_wt
    ):
        # show-ref, show-current, checkout, rev-parse, pull
        mock_run_cmd.side_effect = ["", "other", "", "origin/main", ""]
        mock_is_in_wt.return_value = False

        result = update_target(".", "main")
        self.assertEqual(result, UpdateTargetResult.SUCCESS)
        self.assertEqual(mock_run_cmd.call_count, 5)

    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_raises_error_when_target_branch_does_not_exist(
        self, mock_run_cmd
    ):
        mock_run_cmd.side_effect = GitExecutionError("No such branch")

        with self.assertRaisesRegex(
            GitExecutionError, "Target branch 'main' does not exist locally."
        ):
            update_target(".", "main")

    @patch("git_scripts.git.remote.is_worktree_busy", return_value=False)
    @patch(
        "git_scripts.git.remote.get_other_worktree_path",
        return_value="/wt/main",
    )
    @patch("git_scripts.git.remote.is_in_another_worktree", return_value=True)
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_fast_forwards_target_in_other_worktree(
        self,
        mock_run_cmd,
        mock_is_in_wt,
        mock_get_wt_path,
        mock_is_busy,
    ):
        del mock_is_in_wt, mock_get_wt_path, mock_is_busy
        # show-ref, show-current, fetch, rev-parse @{u}, merge --ff-only
        mock_run_cmd.side_effect = ["", "feat/a", "", "origin/main", ""]

        result = update_target("/wt/feat", "main")

        self.assertEqual(result, UpdateTargetResult.SUCCESS)
        mock_run_cmd.assert_any_call(
            ["git", "merge", "--ff-only", "@{u}"], cwd="/wt/main"
        )

    @patch("git_scripts.git.remote.is_worktree_busy", return_value=False)
    @patch(
        "git_scripts.git.remote.get_other_worktree_path",
        return_value="/wt/main",
    )
    @patch("git_scripts.git.remote.is_in_another_worktree", return_value=True)
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_falls_back_to_fetched_only_when_ff_fails(
        self,
        mock_run_cmd,
        mock_is_in_wt,
        mock_get_wt_path,
        mock_is_busy,
    ):
        del mock_is_in_wt, mock_get_wt_path, mock_is_busy

        def side_effect(cmd, cwd=None, check=True):
            del cwd, check
            if cmd[:2] == ["git", "merge"]:
                raise GitExecutionError("diverged or dirty")
            if cmd[:2] == ["git", "rev-parse"]:
                return "origin/main"
            if cmd[:2] == ["git", "branch"]:
                return "feat/a"
            return ""

        mock_run_cmd.side_effect = side_effect

        result = update_target("/wt/feat", "main")

        self.assertEqual(result, UpdateTargetResult.FETCHED_ONLY)

    @patch("git_scripts.git.remote.is_worktree_busy", return_value=True)
    @patch(
        "git_scripts.git.remote.get_other_worktree_path",
        return_value="/wt/main",
    )
    @patch("git_scripts.git.remote.is_in_another_worktree", return_value=True)
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_returns_fetched_only_when_other_worktree_is_busy(
        self,
        mock_run_cmd,
        mock_is_in_wt,
        mock_get_wt_path,
        mock_is_busy,
    ):
        del mock_is_in_wt, mock_get_wt_path, mock_is_busy
        mock_run_cmd.side_effect = ["", "feat/a", ""]

        result = update_target("/wt/feat", "main")

        self.assertEqual(result, UpdateTargetResult.FETCHED_ONLY)
        self.assertEqual(mock_run_cmd.call_count, 3)

    @patch("git_scripts.git.remote.is_worktree_busy", return_value=False)
    @patch(
        "git_scripts.git.remote.get_other_worktree_path",
        return_value=None,
    )
    @patch("git_scripts.git.remote.is_in_another_worktree", return_value=True)
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_returns_fetched_only_when_worktree_path_missing(
        self,
        mock_run_cmd,
        mock_is_in_wt,
        mock_get_wt_path,
        mock_is_busy,
    ):
        del mock_is_in_wt, mock_get_wt_path
        mock_run_cmd.side_effect = ["", "feat/a", ""]

        result = update_target("/wt/feat", "main")

        self.assertEqual(result, UpdateTargetResult.FETCHED_ONLY)
        self.assertEqual(mock_run_cmd.call_count, 3)
        mock_is_busy.assert_not_called()

    @patch("git_scripts.git.remote.is_worktree_busy", return_value=False)
    @patch(
        "git_scripts.git.remote.get_other_worktree_path",
        return_value="/wt/main",
    )
    @patch("git_scripts.git.remote.is_in_another_worktree", return_value=True)
    @patch("git_scripts.git.remote.run_cmd")
    def test_update_target_returns_local_only_when_worktree_lacks_upstream(
        self,
        mock_run_cmd,
        mock_is_in_wt,
        mock_get_wt_path,
        mock_is_busy,
    ):
        del mock_is_in_wt, mock_get_wt_path, mock_is_busy
        mock_run_cmd.side_effect = ["", "feat/a", "", ""]

        result = update_target("/wt/feat", "main")

        self.assertEqual(result, UpdateTargetResult.LOCAL_ONLY)
        self.assertEqual(mock_run_cmd.call_count, 4)


if __name__ == "__main__":
    absltest.main()
