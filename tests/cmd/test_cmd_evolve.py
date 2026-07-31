import pygit2
from absl.testing import absltest

from git_scripts.cmd.evolve import execute_evolve
from git_scripts.ui import UI
from tests.helpers import GitTestRepo, run_git


class TestCmdEvolve(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo(use_template=True)
        self.repo = pygit2.Repository(self.repo_helper.path)

        # To test evolve, we need a stack that is orphaned by a rebase
        # Master template has:
        # main -> test-chain-a -> test-chain-b -> test-chain-c
        #
        # Let's check out main and create a commit.
        self.repo_helper.checkout("main")
        self.repo_helper.commit("new main", "new_main.txt", "new")

        # Now simulate user doing `git rebase main` while on test-chain-a
        self.repo_helper.checkout("test-chain-a")

        old_head = self.repo.revparse_single("HEAD").id

        # We manually cherry-pick test-chain-a onto main
        # (This mimics rebase moving test-chain-a)
        self.repo_helper.commit("a (rebased)", "a.txt", "a2")

        # Now test-chain-b and c still point to the old test-chain-a
        self.old_hash = str(old_head)
        self.new_hash = str(self.repo.revparse_single("HEAD").id)

    def test_execute_evolve_restores_stack_when_given_explicit_old_hash(self):
        ui = UI(auto_yes=True)
        result = execute_evolve(
            self.repo_helper.path, old_hash=self.old_hash, ui=ui
        )
        self.assertTrue(result)

        c_commit = self.repo.revparse_single("test-chain-a-b-c")
        a_commit = self.repo.revparse_single("test-chain-a")
        merge_base = self.repo.merge_base(c_commit.id, a_commit.id)
        self.assertEqual(merge_base, a_commit.id)

    def test_execute_evolve_restores_stack_by_finding_old_base_via_reflog(
        self,
    ):
        ui = UI(auto_yes=True)
        result = execute_evolve(self.repo_helper.path, old_hash=None, ui=ui)
        self.assertTrue(result)

        c_commit = self.repo.revparse_single("test-chain-a-b-c")
        a_commit = self.repo.revparse_single("test-chain-a")
        merge_base = self.repo.merge_base(c_commit.id, a_commit.id)
        self.assertEqual(merge_base, a_commit.id)

    def test_execute_evolve_restores_stack_via_remote_tracking_branch(
        self,
    ):
        # Simulate a scenario where the reflog is wiped, but the remote
        # tracking branch still points to the old hash.

        # 1. First, create a mock origin remote and push test-chain-a to it
        origin_path = self.repo_helper.path + "_origin.git"
        run_git(["init", "--bare", origin_path], cwd=self.repo_helper.path)
        run_git(
            ["remote", "add", "origin", origin_path], cwd=self.repo_helper.path
        )
        run_git(
            ["push", "origin", f"{self.old_hash}:refs/heads/test-chain-a"],
            cwd=self.repo_helper.path,
        )
        run_git(["fetch", "origin"], cwd=self.repo_helper.path)

        # 2. Wipe the reflog completely so Heuristic 2 (Reflog) fails
        run_git(
            ["reflog", "expire", "--expire=now", "--all"],
            cwd=self.repo_helper.path,
        )

        # 3. Ensure the branch tracks the upstream
        run_git(
            [
                "branch",
                "--set-upstream-to=origin/test-chain-a",
                "test-chain-a",
            ],
            cwd=self.repo_helper.path,
        )

        ui = UI(auto_yes=True)
        # 4. Evolve! It should fallback to tracking branch (Heuristic 1)
        result = execute_evolve(self.repo_helper.path, old_hash=None, ui=ui)
        self.assertTrue(result)

        c_commit = self.repo.revparse_single("test-chain-a-b-c")
        a_commit = self.repo.revparse_single("test-chain-a")
        merge_base = self.repo.merge_base(c_commit.id, a_commit.id)
        self.assertEqual(merge_base, a_commit.id)

    def test_execute_evolve_fails_when_user_aborts_conflict(
        self,
    ):
        self.repo_helper.checkout("test-chain-a-b")
        self.repo_helper.commit("conflict in b", "a.txt", "conflict")

        self.repo_helper.checkout("test-chain-a")

        from unittest.mock import MagicMock

        mock_ui = MagicMock()
        mock_ui.confirm.return_value = True
        mock_ui.ask_choice.return_value = "Abort rebase and rollback"

        result = execute_evolve(
            self.repo_helper.path, old_hash=self.old_hash, ui=mock_ui
        )
        self.assertFalse(result)

    def test_execute_evolve_returns_false_when_given_invalid_old_hash(self):
        ui = UI(auto_yes=True)
        result = execute_evolve(
            self.repo_helper.path, old_hash="invalidhash", ui=ui
        )
        self.assertFalse(result)

    def test_execute_evolve_returns_false_when_user_declines_confirmation(
        self,
    ):
        from unittest.mock import MagicMock

        mock_ui = MagicMock()
        mock_ui.confirm.return_value = False

        result = execute_evolve(
            self.repo_helper.path, old_hash=self.old_hash, ui=mock_ui
        )
        self.assertFalse(result)

    def test_execute_evolve_fails_when_default_ui_declines(
        self,
    ):
        from unittest.mock import patch

        with patch("git_scripts.cmd.evolve.UI") as mock_ui_cls:
            mock_ui = mock_ui_cls.return_value
            mock_ui.confirm.return_value = False
            result = execute_evolve(
                self.repo_helper.path, old_hash=self.old_hash, ui=None
            )
            self.assertFalse(result)

    def test_execute_evolve_returns_true_when_no_branches_are_displaced(self):
        ui = UI(auto_yes=True)
        result = execute_evolve(
            self.repo_helper.path, old_hash=self.new_hash, ui=ui
        )
        self.assertTrue(result)

    def test_execute_evolve_fails_when_old_base_undetected(
        self,
    ):
        ui = UI(auto_yes=True)
        run_git(
            ["reflog", "expire", "--expire=now", "--all"],
            cwd=self.repo_helper.path,
        )
        result = execute_evolve(self.repo_helper.path, old_hash=None, ui=ui)
        self.assertFalse(result)

    def test_execute_evolve_returns_false_when_worktree_is_busy(self):
        from unittest.mock import MagicMock, patch

        mock_ui = MagicMock()
        mock_ui.confirm.return_value = True

        with patch("git_scripts.cmd.evolve.manage_worktrees") as mock_mw:
            mock_wt_state = MagicMock()
            mock_wt_state.failed_branches = {"test-chain-a-b-c"}
            mock_mw.return_value.__enter__.return_value = mock_wt_state

            result = execute_evolve(
                self.repo_helper.path, old_hash=self.old_hash, ui=mock_ui
            )
            self.assertFalse(
                result
            )  # It should fail because it skips and logs failure
