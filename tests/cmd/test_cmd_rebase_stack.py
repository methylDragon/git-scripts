from unittest import mock

import pygit2
from absl.testing import absltest

from git_scripts.cmd.rebase_stack import execute_rebase_stack
from git_scripts.ui import UI
from tests.helpers import GitTestRepo


class MockUI(UI):
    def __init__(self, auto_yes: bool = True):
        super().__init__(plain=True, auto_yes=auto_yes)
        self.prints = []

    def print(self, *args, **kwargs):
        self.prints.extend(args)


class TestCmdRebaseStack(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()

    def tearDown(self):
        self.repo_helper.cleanup()

    @mock.patch("git_scripts.cmd.rebase_stack.push_branches")
    def test_execute_rebase_stack_linear_chain(self, mock_push):
        # Master template:
        # main
        # ├── test-chain-a
        # │   └── test-chain-a-b
        # │       └── test-chain-a-b-c (tip)
        # └── test-chain-d
        #     └── test-chain-d-e ...

        old_d_hash = self.repo_helper.rev_parse("test-chain-d")

        self.repo_helper.checkout("main")
        self.repo_helper.commit("main-update")

        # Checkout intermediate branch in chain A
        self.repo_helper.checkout("test-chain-a-b")

        ui = MockUI(auto_yes=True)

        def verify_restored(*args, **kwargs):
            current = self.repo_helper.get_pygit2_repo().head.shorthand
            self.assertEqual(current, "test-chain-a-b")

        mock_push.side_effect = verify_restored

        success = execute_rebase_stack(
            repo_path=self.repo_helper.path,
            target="main",
            all_worktrees=False,
            auto_delete=False,
            ui=ui,
        )
        self.assertTrue(success)
        mock_push.assert_called_once()

        # Check restored branch
        current = self.repo_helper.get_pygit2_repo().head.shorthand
        self.assertEqual(current, "test-chain-a-b")

        # Assert topological relationships for chain A
        self._assert_parent("main", "test-chain-a")
        self._assert_parent("test-chain-a", "test-chain-a-b")
        self._assert_parent("test-chain-a-b", "test-chain-a-b-c")

        # Ensure chain D was completely untouched
        self.assertEqual(
            self.repo_helper.rev_parse("test-chain-d"), old_d_hash
        )

    @mock.patch("git_scripts.cmd.rebase_stack.push_branches")
    def test_execute_rebase_stack_preserves_colocated_branches(
        self, mock_push
    ):
        self.repo_helper.checkout("main")
        self.repo_helper.commit("main-base", "main_base.txt", "base")

        # branch A
        self.repo_helper.checkout("stk/A", create=True)
        self.repo_helper.commit("A commit", "a.txt", "a")

        # branch B (co-located with A)
        self.repo_helper.checkout("stk/B", create=True)

        # branch C (child of A)
        self.repo_helper.checkout("stk/A")
        self.repo_helper.checkout("stk/C", create=True)
        self.repo_helper.commit("C commit", "c.txt", "c")

        # Update main
        self.repo_helper.checkout("main")
        self.repo_helper.commit("main updated", "main.txt", "updated")

        self.repo_helper.checkout("stk/B")

        ui = MockUI(auto_yes=True)
        success = execute_rebase_stack(
            repo_path=self.repo_helper.path,
            target="main",
            all_worktrees=False,
            auto_delete=False,
            ui=ui,
        )
        self.assertTrue(success)

        self._assert_parent("main", "stk/A")
        self.assertEqual(
            self.repo_helper.rev_parse("stk/A"),
            self.repo_helper.rev_parse("stk/B"),
        )
        self._assert_parent("stk/A", "stk/C")

    @mock.patch("git_scripts.cmd.rebase_stack.push_branches")
    def test_execute_rebase_stack_fork_detected_aborts(self, mock_push):
        # test-chain-d-e-f has two children:
        # test-chain-d-e-f-g and test-chain-d-e-f-j
        self.repo_helper.checkout("test-chain-d-e-f")

        ui = MockUI(auto_yes=True)
        success = execute_rebase_stack(
            repo_path=self.repo_helper.path,
            target="main",
            ui=ui,
        )
        self.assertFalse(success)
        mock_push.assert_not_called()
        self.assertTrue(
            any("Fork detected downstream" in str(p) for p in ui.prints)
        )

    @mock.patch("git_scripts.cmd.rebase_stack.push_branches")
    def test_execute_rebase_stack_from_fork_leaf_succeeds(self, mock_push):
        # When checked out on the tip of one branch of the fork,
        # it is a strictly linear path from main up to that tip.
        self.repo_helper.checkout("test-chain-d-e-f-g-h-i")

        old_j_hash = self.repo_helper.rev_parse("test-chain-d-e-f-j-k-l")

        self.repo_helper.checkout("main")
        self.repo_helper.commit("main update for fork test")

        self.repo_helper.checkout("test-chain-d-e-f-g-h-i")

        ui = MockUI(auto_yes=True)
        success = execute_rebase_stack(
            repo_path=self.repo_helper.path,
            target="main",
            all_worktrees=False,
            auto_delete=False,
            ui=ui,
        )
        self.assertTrue(success)

        # G fork path is rebased onto main
        self._assert_parent("main", "test-chain-d")
        self._assert_parent("test-chain-d", "test-chain-d-e")
        self._assert_parent("test-chain-d-e", "test-chain-d-e-f")
        self._assert_parent("test-chain-d-e-f", "test-chain-d-e-f-g")
        self._assert_parent("test-chain-d-e-f-g", "test-chain-d-e-f-g-h")
        self._assert_parent("test-chain-d-e-f-g-h", "test-chain-d-e-f-g-h-i")

        # J fork was untouched
        self.assertEqual(
            self.repo_helper.rev_parse("test-chain-d-e-f-j-k-l"), old_j_hash
        )

    def test_execute_rebase_stack_detached_head(self):
        repo = pygit2.Repository(self.repo_helper.path)
        c = repo.revparse_single("main")
        repo.checkout_tree(c)
        repo.set_head(c.id)

        ui = MockUI()
        success = execute_rebase_stack(
            repo_path=self.repo_helper.path,
            target="main",
            ui=ui,
        )
        self.assertFalse(success)
        self.assertTrue(any("detached HEAD" in str(p) for p in ui.prints))

    def test_execute_rebase_stack_on_target_branch(self):
        self.repo_helper.checkout("main")
        ui = MockUI()
        success = execute_rebase_stack(
            repo_path=self.repo_helper.path,
            target="main",
            ui=ui,
        )
        self.assertTrue(success)
        self.assertTrue(
            any(
                "Current branch is target branch 'main'" in str(p)
                for p in ui.prints
            )
        )

    def test_execute_rebase_stack_no_branches_in_stack(self):
        self.repo_helper.checkout("test-chain-a")
        with mock.patch(
            "git_scripts.cmd.rebase_stack._get_linear_stack",
            return_value=set(),
        ):
            ui = MockUI()
            success = execute_rebase_stack(
                repo_path=self.repo_helper.path,
                target="main",
                ui=ui,
            )
            self.assertTrue(success)
            self.assertTrue(
                any("No branches found in stack" in str(p) for p in ui.prints)
            )

    def _assert_parent(self, parent_branch: str, child_branch: str):
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
