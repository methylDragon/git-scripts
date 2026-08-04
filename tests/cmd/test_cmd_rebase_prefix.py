from unittest import mock

from absl.testing import absltest

from git_scripts.cmd.rebase_prefix import execute_rebase_prefix
from git_scripts.ui import UI
from tests.helpers import GitTestRepo


class TestCmdRebasePrefix(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()

    def tearDown(self):
        self.repo_helper.cleanup()

    @mock.patch("git_scripts.cmd.rebase_prefix.prompt_and_push_branches")
    def test_execute_rebase_prefix_rebases_linear_and_forking_chains(
        self, mock_push
    ):
        self.repo_helper.checkout("main")
        self.repo_helper.commit("main-update")

        # Act
        ui = UI(auto_yes=True)

        # Verify it restores to the initially checked-out branch
        self.repo_helper.checkout("test-chain-a")

        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="test-chain-",
            target="main",
            all_worktrees=False,
            auto_delete=False,  # Keep merged branches to assert on them
            ui=ui,
        )
        self.assertTrue(success)

        # Check that we are back on test-chain-a
        current_branch = self.repo_helper.get_pygit2_repo().head.shorthand
        self.assertEqual(current_branch, "test-chain-a")

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

    @mock.patch("git_scripts.cmd.rebase_prefix.prompt_and_push_branches")
    def test_execute_rebase_prefix_preserves_stack_with_colocated_branches(
        self, mock_push
    ):
        # main
        #  └─ ch3/A
        #      ├─ ch3/B  (same commit as A)
        #      └─ ch3/C  (child of A)

        self.repo_helper.checkout("main")
        self.repo_helper.commit("main-base", "main_base.txt", "base")

        # branch A
        self.repo_helper.checkout("ch3/A", create=True)
        self.repo_helper.commit("A commit", "a.txt", "a")

        # branch B (co-located with A)
        self.repo_helper.checkout("ch3/B", create=True)

        # branch C (child of A)
        self.repo_helper.checkout("ch3/A")
        self.repo_helper.checkout("ch3/C", create=True)
        self.repo_helper.commit("C commit", "c.txt", "c")

        # Update main to force a rebase
        self.repo_helper.checkout("main")
        self.repo_helper.commit("main updated", "main.txt", "updated")

        ui = UI(auto_yes=True)
        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="ch3/",
            target="main",
            all_worktrees=False,
            auto_delete=False,
            ui=ui,
        )
        self.assertTrue(success)

        # After the rebase, check branches directly instead of via rev_parse
        # A should be rebased onto main
        self._assert_parent("main", "ch3/A")

        # B should still be at exactly A (co-located)
        self.assertEqual(
            self.repo_helper.rev_parse("ch3/A"),
            self.repo_helper.rev_parse("ch3/B"),
        )

        # C should still be a child of A
        self._assert_parent("ch3/A", "ch3/C")

    def _assert_parent(self, parent_branch: str, child_branch: str):
        # child_branch~1 should equal parent_branch
        parent_hash = self.repo_helper.rev_parse(parent_branch)
        try:
            child_parent_hash = self.repo_helper.rev_parse(f"{child_branch}~1")
        except Exception:
            self.fail(f"Could not resolve parent of {child_branch}")
        self.assertEqual(
            parent_hash,
            child_parent_hash,
            f"{parent_branch} is not parent of {child_branch}",
        )


if __name__ == "__main__":
    absltest.main()
