from unittest import mock

import pygit2
from absl.testing import absltest

from git_scripts.cmd.push_prefix import execute_push_prefix
from git_scripts.ui import UI
from tests.helpers import GitTestRepo


class TestCmdPushPrefix(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo(use_template=True)
        self.repo = pygit2.Repository(self.repo_helper.path)

        # Create branches matching prefix
        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("feat1", "f1.txt", "1")

        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("feat2", "f2.txt", "2")

        # We need to simulate remotes.
        # Best way is to just create the refs manually.
        feat1_id = self.repo.revparse_single("feat/1").id

        # Set up origin/feat/1 exactly same as feat/1
        self.repo.references.create("refs/remotes/origin/feat/1", feat1_id)

        # Set up origin/feat/2 pointing to an older commit (main)
        main_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/feat/2", main_id)

    @mock.patch("git_scripts.cmd.push_prefix.run_cmd")
    @mock.patch("git_scripts.cmd.push_prefix.push_branches")
    def test_execute_push_prefix_skips_up_to_date_branches(
        self, mock_push_branches, mock_run_cmd
    ):
        mock_push_branches.return_value = True

        ui = UI(auto_yes=True)
        with mock.patch.object(ui, "ask_choice", return_value="Push all"):
            result = execute_push_prefix(
                self.repo_helper.path, prefix="feat/", ui=ui
            )

        self.assertTrue(result)
        # origin/feat/1 is up to date, so it should be skipped
        # origin/feat/2 is out of date, so it should be pushed
        mock_push_branches.assert_called_once_with(
            ["feat/2"], [], repo_path=self.repo_helper.path
        )
        mock_run_cmd.assert_called_once()  # For the git fetch

    @mock.patch("git_scripts.cmd.push_prefix.run_cmd")
    @mock.patch("git_scripts.cmd.push_prefix.push_branches")
    def test_execute_push_prefix_does_nothing_if_all_up_to_date(
        self, mock_push_branches, mock_run_cmd
    ):
        # Update origin/feat/2 to be up to date
        feat2_id = self.repo.revparse_single("feat/2").id
        self.repo.references["refs/remotes/origin/feat/2"].set_target(feat2_id)

        result = execute_push_prefix(self.repo_helper.path, prefix="feat/")

        self.assertTrue(result)
        mock_push_branches.assert_not_called()

    @mock.patch("git_scripts.cmd.push_prefix.run_cmd")
    @mock.patch("git_scripts.cmd.push_prefix.push_branches")
    def test_execute_push_prefix_returns_false_if_push_fails(
        self, mock_push_branches, mock_run_cmd
    ):
        mock_push_branches.return_value = False

        ui = UI(auto_yes=True)
        with mock.patch.object(ui, "ask_choice", return_value="Push all"):
            result = execute_push_prefix(
                self.repo_helper.path, prefix="feat/", ui=ui
            )

        self.assertFalse(result)

    @mock.patch("git_scripts.cmd.push_prefix.run_cmd")
    @mock.patch("git_scripts.cmd.push_prefix.push_branches")
    def test_execute_push_prefix_pushes_new_branch(
        self, mock_push_branches, mock_run_cmd
    ):
        mock_push_branches.return_value = True

        self.repo_helper.checkout("feat/3", create=True)
        self.repo_helper.commit("feat3", "f3.txt", "3")

        ui = UI(auto_yes=True)
        with mock.patch.object(ui, "ask_choice", return_value="Push all"):
            result = execute_push_prefix(
                self.repo_helper.path, prefix="feat/3", ui=ui
            )

        self.assertTrue(result)
        mock_push_branches.assert_called_once_with(
            ["feat/3"], [], repo_path=self.repo_helper.path
        )
