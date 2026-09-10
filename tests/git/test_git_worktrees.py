import os
from unittest.mock import MagicMock

from absl.testing import absltest

from git_scripts.git.core import run_cmd
from git_scripts.git.worktrees import (
    WorktreeLifecycleCallbacks,
    manage_worktrees,
)
from tests.helpers import GitTestRepo


class TestGitWorktrees(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()
        self.repo = self.repo_helper.get_pygit2_repo()

    def tearDown(self):
        self.repo_helper.cleanup()

    def test_manage_worktrees_detaches_and_reattaches_branches(self):
        # Create a worktree for a branch
        worktree_path = os.path.join(self.repo_helper.temp_dir.name, "wt_a")
        self.repo_helper.create_worktree(worktree_path, "test-chain-a")

        mock_on_detach = MagicMock()
        mock_on_reattach = MagicMock()

        mock_callbacks = WorktreeLifecycleCallbacks(
            on_detach=mock_on_detach,
            on_reattach=mock_on_reattach,
        )

        # Test Context Manager
        with manage_worktrees(
            "test-chain-",
            active=True,
            repo_path=self.repo_helper.path,
            callbacks=mock_callbacks,
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
            mock_on_detach.assert_called_once_with(
                worktree_path, "test-chain-a"
            )

        # Ensure branch is reattached
        out = run_cmd(["git", "branch", "--show-current"], cwd=worktree_path)
        self.assertEqual(out, "test-chain-a")
        mock_on_reattach.assert_called_once_with(worktree_path, "test-chain-a")

    def test_manage_worktrees_with_target_branches_only_detaches_targets(self):
        # Create two worktrees
        wt_a = os.path.join(self.repo_helper.temp_dir.name, "wt_a")
        self.repo_helper.create_worktree(wt_a, "test-chain-a")

        run_cmd(
            ["git", "branch", "test-chain-b", "HEAD"],
            cwd=self.repo_helper.path,
            check=False,
        )
        wt_b = os.path.join(self.repo_helper.temp_dir.name, "wt_b")
        self.repo_helper.create_worktree(wt_b, "test-chain-b")

        # Use manage_worktrees targeting only "test-chain-a"
        with manage_worktrees(
            active=True,
            repo_path=self.repo_helper.path,
            target_branches=["test-chain-a"],
        ) as wt_state:
            # wt_a should be detached
            self.assertIn(wt_a, wt_state.detached_map)
            self.assertEqual(wt_state.detached_map[wt_a], "test-chain-a")
            out_a = run_cmd(["git", "branch", "--show-current"], cwd=wt_a)
            self.assertEqual(out_a, "")  # detached HEAD

            # wt_b should not be detached
            self.assertNotIn(wt_b, wt_state.detached_map)
            out_b = run_cmd(["git", "branch", "--show-current"], cwd=wt_b)
            self.assertEqual(out_b, "test-chain-b")

        # After exiting the context manager, both should be reattached
        out_a = run_cmd(["git", "branch", "--show-current"], cwd=wt_a)
        self.assertEqual(out_a, "test-chain-a")


if __name__ == "__main__":
    absltest.main()
