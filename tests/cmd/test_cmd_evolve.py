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

    def test_execute_evolve_rebases_descendants_given_explicit_hash(self):
        # Find test-chain-a-b and a-b-c and rebase them onto test-chain-a.
        ui = UI(auto_yes=True)
        result = execute_evolve(
            self.repo_helper.path, old_hash=self.old_hash, ui=ui
        )
        self.assertTrue(result)

        # Check that test-chain-a-b-c is now based on the new test-chain-a
        c_commit = self.repo.revparse_single("test-chain-a-b-c")
        a_commit = self.repo.revparse_single("test-chain-a")

        # a_commit should be an ancestor of c_commit
        merge_base = self.repo.merge_base(c_commit.id, a_commit.id)
        self.assertEqual(merge_base, a_commit.id)

    def test_execute_evolve_rebases_descendants_using_reflog_heuristic(self):
        # Do not mock get_previous_head. Let it naturally find the old base!
        # Because we just did a commit in setUp() while on test-chain-a,
        # the reflog HEAD@{1} naturally points to old_hash before the commit.
        ui = UI(auto_yes=True)
        result = execute_evolve(self.repo_helper.path, old_hash=None, ui=ui)
        self.assertTrue(result)

        c_commit = self.repo.revparse_single("test-chain-a-b-c")
        a_commit = self.repo.revparse_single("test-chain-a")
        merge_base = self.repo.merge_base(c_commit.id, a_commit.id)
        self.assertEqual(merge_base, a_commit.id)

    def test_execute_evolve_rebases_descendants_using_tracking_branch(self):
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
