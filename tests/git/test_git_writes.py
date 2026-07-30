import os

from absl.testing import absltest

from git_scripts.git.writes import manage_worktrees, run_cmd
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


if __name__ == "__main__":
    absltest.main()
