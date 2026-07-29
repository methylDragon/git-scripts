from absl.testing import absltest

from git_scripts.cmd.rebase_prefix import execute_rebase_prefix
from git_scripts.ui import UI
from tests.helpers import GitTestRepo


class TestCmdRebasePrefix(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()

    def tearDown(self):
        self.repo_helper.cleanup()

    def test_execute_rebase_prefix_rebases_linear_and_forking_chains(self):
        self.repo_helper.checkout("main")
        self.repo_helper.commit("main-update")

        # Act
        ui = UI(auto_yes=True)

        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="test-chain-",
            target="main",
            all_worktrees=False,
            auto_delete=False,  # Keep merged branches to assert on them
            ui=ui,
        )
        self.assertTrue(success)

        # Assert topological relationships
        # a stack
        self._assert_parent("main", "test-chain-a")
        self._assert_parent("test-chain-a", "test-chain-a-b")
        self._assert_parent("test-chain-a-b", "test-chain-a-b-c")

        # d stack
        self._assert_parent("main", "test-chain-d")
        self._assert_parent("test-chain-d", "test-chain-d-e")
        self._assert_parent("test-chain-d-e", "test-chain-d-e-f")

        # g fork
        self._assert_parent("test-chain-d-e-f", "test-chain-d-e-f-g")
        self._assert_parent("test-chain-d-e-f-g", "test-chain-d-e-f-g-h")
        self._assert_parent("test-chain-d-e-f-g-h", "test-chain-d-e-f-g-h-i")

        # j fork
        self._assert_parent("test-chain-d-e-f", "test-chain-d-e-f-j")
        self._assert_parent("test-chain-d-e-f-j", "test-chain-d-e-f-j-k")
        self._assert_parent("test-chain-d-e-f-j-k", "test-chain-d-e-f-j-k-l")

    def _assert_parent(self, parent_branch: str, child_branch: str):
        # child_branch~1 should equal parent_branch
        parent_hash = self.repo_helper.rev_parse(parent_branch)
        child_parent_hash = self.repo_helper.rev_parse(f"{child_branch}~1")
        self.assertEqual(
            parent_hash,
            child_parent_hash,
            f"{parent_branch} is not parent of {child_branch}",
        )


if __name__ == "__main__":
    absltest.main()
