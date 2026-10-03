from unittest import mock

import pygit2
from absl.testing import absltest

from git_scripts.cmd.prune_local import execute_prune_local
from git_scripts.cmd.prune_remote_prefix import execute_prune_remote_prefix
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

    def test_execute_prune_local_categorizes_obsolete_and_unmerged_no_upstream(
        self,
    ):
        """Verifies --also-prune-no-upstream buckets merged and unmerged."""
        clean_helper = GitTestRepo(use_template=False)
        self.addCleanup(clean_helper.cleanup)
        clean_repo = pygit2.Repository(clean_helper.path)

        # Create an untracked branch merged into main (obsolete)
        clean_helper.checkout("ch3/merged", create=True)
        clean_helper.commit("m1", "m1.txt", "merged")
        merged_id = clean_repo.revparse_single("ch3/merged").id
        clean_helper.checkout("main")
        clean_repo.references.create("refs/heads/main", merged_id, force=True)

        # Create an untracked branch with unmerged commits
        clean_helper.checkout("ch3/unmerged", create=True)
        clean_helper.commit("u1", "u1.txt", "unmerged")

        # Create a tracked branch with active upstream (must not be pruned)
        clean_helper.add_remote("origin", "https://example.com/repo.git")
        clean_helper.checkout("ch3/tracked", create=True)
        clean_helper.commit("t1", "t1.txt", "tracked")
        tracked_id = clean_repo.revparse_single("ch3/tracked").id
        clean_repo.references.create(
            "refs/remotes/origin/ch3/tracked", tracked_id, force=True
        )
        clean_repo.branches.local[
            "ch3/tracked"
        ].upstream = clean_repo.branches.remote["origin/ch3/tracked"]

        # Create a branch checked out in another worktree
        clean_helper.checkout("ch3/in-worktree", create=True)
        clean_helper.commit("w1", "w1.txt", "worktree")
        clean_helper.checkout("main")

        with mock.patch("git_scripts.cmd.prune_local.run_cmd") as mock_run_cmd:

            def mock_run(cmd, cwd=None, check=True):
                del cwd, check
                if cmd == ["git", "worktree", "list", "--porcelain"]:
                    return (
                        "branch refs/heads/main\n"
                        "branch refs/heads/ch3/in-worktree\n"
                    )
                return ""

            mock_run_cmd.side_effect = mock_run

            # User deletes orphaned/obsolete bucket, skips unmerged bucket
            with mock.patch(
                "git_scripts.ui.UI.ask_choice",
                side_effect=["Delete all", "Skip all"],
            ) as mock_ask:
                result = execute_prune_local(
                    clean_helper.path,
                    dry_run=False,
                    also_prune_no_upstream=True,
                )
            self.assertTrue(result)
            self.assertEqual(mock_ask.call_count, 2)
            mock_run_cmd.assert_any_call(
                ["git", "branch", "-D", "ch3/merged"],
                cwd=clean_helper.path,
            )

            # User deletes both buckets
            mock_run_cmd.reset_mock()
            with mock.patch(
                "git_scripts.ui.UI.ask_choice",
                side_effect=["Delete all", "Delete all"],
            ):
                result = execute_prune_local(
                    clean_helper.path,
                    dry_run=False,
                    also_prune_no_upstream=True,
                )
            self.assertTrue(result)
            mock_run_cmd.assert_any_call(
                ["git", "branch", "-D", "ch3/merged", "ch3/unmerged"],
                cwd=clean_helper.path,
            )

            # Missing target ref conservatively buckets untracked as unmerged
            # and supports interactive checkbox selection
            mock_run_cmd.reset_mock()
            with (
                mock.patch(
                    "git_scripts.ui.UI.ask_choice",
                    return_value="Select which to delete",
                ) as mock_ask_missing,
                mock.patch(
                    "git_scripts.ui.UI.ask_checkbox",
                    return_value=["ch3/unmerged"],
                ) as mock_checkbox,
            ):
                result = execute_prune_local(
                    clean_helper.path,
                    dry_run=False,
                    also_prune_no_upstream=True,
                    target="nonexistent",
                )
            self.assertTrue(result)
            mock_ask_missing.assert_called_once()
            mock_checkbox.assert_called_once_with(
                "Select unmerged local branches to delete:",
                choices=["ch3/merged", "ch3/unmerged"],
            )
            mock_run_cmd.assert_any_call(
                ["git", "branch", "-D", "ch3/unmerged"],
                cwd=clean_helper.path,
            )

    @mock.patch("git_scripts.cmd.prune_remote_prefix.subprocess_run")
    def test_execute_prune_remote_prefix_deletes_merged_branches(
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

        # run prune_remote_prefix
        with mock.patch(
            "git_scripts.ui.UI.ask_choice", return_value="Delete all"
        ):
            result = execute_prune_remote_prefix(
                self.repo_helper.path, prefix="feat/"
            )
        self.assertTrue(result)

        # It should call git push origin --delete feat/1
        mock_subprocess_run.assert_any_call(
            ["git", "push", "origin", "--delete", "feat/1"],
            cwd=self.repo_helper.path,
            check=True,
        )

    @mock.patch("git_scripts.cmd.prune_remote_prefix.subprocess_run")
    def test_execute_prune_remote_prefix_skips_deletion_in_dry_run_mode(
        self, mock_subprocess_run
    ):
        main_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/main", main_id)
        self.repo.references.create("refs/remotes/origin/feat/1", main_id)

        with mock.patch(
            "git_scripts.ui.UI.ask_choice", return_value="Delete all"
        ):
            result = execute_prune_remote_prefix(
                self.repo_helper.path, prefix="feat/", dry_run=True
            )
        self.assertTrue(result)

        for call in mock_subprocess_run.call_args_list:
            args, kwargs = call
            if args and args[0][0] == "git" and args[0][1] == "push":
                self.fail("git push called during dry run")

    @mock.patch("git_scripts.cmd.prune_remote_prefix.subprocess_run")
    def test_execute_prune_remote_prefix_deletes_orphan_with_no_local_flag(
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
            result = execute_prune_remote_prefix(
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
