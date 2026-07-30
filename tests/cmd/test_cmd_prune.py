from unittest import mock

import pygit2
from absl.testing import absltest

from git_scripts.cmd.prune_local import execute_prune_local
from git_scripts.cmd.prune_remote import execute_prune_remote
from tests.helpers import GitTestRepo


class TestCmdPrune(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo(use_template=True)
        self.repo = pygit2.Repository(self.repo_helper.path)

    def test_execute_prune_local_deletes_merged_branches(self):
        # Create some local branches
        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("f1", "f1.txt", "1")
        f1_id = self.repo.revparse_single("feat/1").id

        self.repo_helper.checkout("main")

        # Merge feat/1 into main
        self.repo.references.create("refs/heads/main", f1_id, force=True)

        # Now feat/1 is fully merged and should be pruned
        # Let's also create an unmerged branch
        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("f2", "f2.txt", "2")
        self.repo_helper.checkout("main")

        with mock.patch("git_scripts.cmd.prune_local.run_cmd") as mock_run_cmd:
            # We mock the git branch -vv output
            def mock_run(cmd, cwd=None, check=True):
                if cmd == ["git", "branch", "-vv"]:
                    return (
                        "  feat/1    abcdef [origin/feat/1: gone] message\n"
                        "* feat/2    123456 message"
                    )
                elif cmd == ["git", "worktree", "list", "--porcelain"]:
                    return ""
                # For `git branch -D` we mock run_cmd to intercept everything.
                # So we just mock the return values for read commands.
                # To verify delete we can just assert it was called.
                return ""

            mock_run_cmd.side_effect = mock_run

            with mock.patch(
                "git_scripts.ui.UI.ask_choice", return_value="Delete all"
            ):
                result = execute_prune_local(
                    self.repo_helper.path, dry_run=False
                )
            self.assertTrue(result)

            # Check if it tried to delete feat/1
            mock_run_cmd.assert_any_call(
                ["git", "branch", "-D", "feat/1"], cwd=self.repo_helper.path
            )

    def test_execute_prune_local_ignores_worktrees_and_dry_run(self):
        with mock.patch("git_scripts.cmd.prune_local.run_cmd") as mock_run_cmd:

            def mock_run(cmd, cwd=None, check=True):
                if cmd == ["git", "branch", "-vv"]:
                    return (
                        "  feat/1    abcdef [origin/feat/1: gone] message\n"
                        "  feat/3    abcdef [origin/feat/3: gone] message\n"
                        "* feat/2    123456 message"
                    )
                elif cmd == ["git", "worktree", "list", "--porcelain"]:
                    return "branch refs/heads/feat/3\n"
                return ""

            mock_run_cmd.side_effect = mock_run

            # Test worktree exclusion
            with mock.patch(
                "git_scripts.ui.UI.ask_choice", return_value="Delete all"
            ):
                result = execute_prune_local(
                    self.repo_helper.path, dry_run=False
                )
            self.assertTrue(result)

            # Should delete feat/1, but NOT feat/3 because it's in a worktree
            mock_run_cmd.assert_any_call(
                ["git", "branch", "-D", "feat/1"], cwd=self.repo_helper.path
            )
            # Make sure it didn't call it with feat/3
            for call in mock_run_cmd.call_args_list:
                args, kwargs = call
                if (
                    args
                    and args[0][0] == "git"
                    and args[0][1] == "branch"
                    and args[0][2] == "-D"
                ):
                    self.assertNotIn("feat/3", args[0])

            # Test dry_run
            mock_run_cmd.reset_mock()
            with mock.patch(
                "git_scripts.ui.UI.ask_choice", return_value="Delete all"
            ):
                result = execute_prune_local(
                    self.repo_helper.path, dry_run=True
                )
            self.assertTrue(result)

            # Should NOT call branch -D on dry run
            for call in mock_run_cmd.call_args_list:
                args, kwargs = call
                if (
                    args
                    and args[0][0] == "git"
                    and args[0][1] == "branch"
                    and args[0][2] == "-D"
                ):
                    self.fail("git branch -D called during dry run")

    @mock.patch("git_scripts.cmd.prune_remote.subprocess_run")
    def test_execute_prune_remote_deletes_merged_branches(
        self, mock_subprocess_run
    ):
        # Create some remote branches
        main_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/main", main_id)

        f1_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/feat/1", f1_id)

        # Create unmerged remote branch
        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("f2", "f2.txt", "2")
        f2_id = self.repo.revparse_single("feat/2").id
        self.repo.references.create("refs/remotes/origin/feat/2", f2_id)
        self.repo_helper.checkout("main")

        # run prune_remote
        with mock.patch(
            "git_scripts.ui.UI.ask_choice", return_value="Delete all"
        ):
            result = execute_prune_remote(
                self.repo_helper.path, prefix="feat/"
            )
        self.assertTrue(result)

        # It should call git push origin --delete feat/1
        mock_subprocess_run.assert_any_call(
            ["git", "push", "origin", "--delete", "feat/1"],
            cwd=self.repo_helper.path,
            check=True,
        )

    @mock.patch("git_scripts.cmd.prune_remote.subprocess_run")
    def test_execute_prune_remote_dry_run(self, mock_subprocess_run):
        main_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/main", main_id)
        self.repo.references.create("refs/remotes/origin/feat/1", main_id)

        with mock.patch(
            "git_scripts.ui.UI.ask_choice", return_value="Delete all"
        ):
            result = execute_prune_remote(
                self.repo_helper.path, prefix="feat/", dry_run=True
            )
        self.assertTrue(result)

        for call in mock_subprocess_run.call_args_list:
            args, kwargs = call
            if args and args[0][0] == "git" and args[0][1] == "push":
                self.fail("git push called during dry run")

    @mock.patch("git_scripts.cmd.prune_remote.subprocess_run")
    def test_execute_prune_remote_with_also_prune_no_local(
        self, mock_subprocess_run
    ):
        main_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/main", main_id)

        # Create unmerged remote branch that has no matching local branch
        self.repo_helper.checkout("feat/orphaned", create=True)
        self.repo_helper.commit("orphaned", "o.txt", "o")
        orphaned_id = self.repo.revparse_single("feat/orphaned").id
        self.repo.references.create(
            "refs/remotes/origin/feat/orphaned", orphaned_id
        )

        # Now delete the local branch so it is truly orphaned
        self.repo_helper.checkout("main")
        self.repo.branches.delete("feat/orphaned")

        # Create unmerged remote branch that DOES have a matching local branch
        self.repo_helper.checkout("feat/active", create=True)
        self.repo_helper.commit("active", "a.txt", "a")
        active_id = self.repo.revparse_single("feat/active").id
        self.repo.references.create(
            "refs/remotes/origin/feat/active", active_id
        )

        with mock.patch(
            "git_scripts.ui.UI.ask_choice", return_value="Delete all"
        ):
            result = execute_prune_remote(
                self.repo_helper.path, prefix="feat/", also_prune_no_local=True
            )
        self.assertTrue(result)

        # It should delete feat/orphaned because it lacks a local branch
        mock_subprocess_run.assert_any_call(
            ["git", "push", "origin", "--delete", "feat/orphaned"],
            cwd=self.repo_helper.path,
            check=True,
        )

        # It should NOT delete feat/active
        for call in mock_subprocess_run.call_args_list:
            args, kwargs = call
            if args and args[0][0] == "git" and args[0][1] == "push":
                self.assertNotIn("feat/active", args[0])
