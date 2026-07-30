from collections.abc import Sequence
from unittest import mock

import pygit2
import questionary
from absl.testing import absltest

from git_scripts.cmd.push_stack import execute_push_stack
from git_scripts.ui import UI
from tests.helpers import GitTestRepo


class MockUI(UI):
    def __init__(self, choices=None):
        super().__init__(plain=True, auto_yes=False)
        self.prints = []
        self._choices = choices or []
        self._choice_idx = 0

    def print(self, *args, **kwargs):
        self.prints.extend(args)

    def ask_choice(
        self, msg: str, choices: list[str], default: str | None = None
    ) -> str:
        if self._choice_idx < len(self._choices):
            val = self._choices[self._choice_idx]
            self._choice_idx += 1
            return val
        return default or choices[0]

    def ask_checkbox(
        self, msg: str, choices: Sequence[str | questionary.Choice]
    ) -> list[str]:
        if self._choice_idx < len(self._choices):
            val = self._choices[self._choice_idx]
            self._choice_idx += 1
            return val
        return [
            str(c.value) if isinstance(c, questionary.Choice) else str(c)
            for c in choices
        ]


class TestCmdPushStack(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo(use_template=True)
        self.repo = pygit2.Repository(self.repo_helper.path)

    @mock.patch("git_scripts.cmd.push_stack.run_cmd")
    @mock.patch("git_scripts.cmd.push_stack.push_branches")
    def test_execute_push_stack_with_push(
        self, mock_push_branches, mock_run_cmd
    ):
        mock_push_branches.return_value = True

        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("feat1", "f1.txt", "1")

        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("feat2", "f2.txt", "2")

        # mock remotes
        main_id = self.repo.revparse_single("main").id
        self.repo.references.create("refs/remotes/origin/feat/1", main_id)
        self.repo.references.create("refs/remotes/origin/feat/2", main_id)

        ui = MockUI(choices=["Push all"])

        # We are on feat/2
        result = execute_push_stack(
            self.repo_helper.path, target="main", ui=ui
        )
        self.assertTrue(result)

        mock_push_branches.assert_called_once_with(
            ["feat/1", "feat/2"], [], repo_path=self.repo_helper.path
        )
        print("PRINTS WITH PUSH:", ui.prints)
        assert any(
            "Found 2 branches to push" in str(getattr(p, "title", str(p)))
            for p in ui.prints
        )

    @mock.patch("git_scripts.cmd.push_stack.run_cmd")
    @mock.patch("git_scripts.cmd.push_stack.push_branches")
    def test_execute_push_stack_fork_aborts(
        self, mock_push_branches, mock_run_cmd
    ):
        mock_push_branches.return_value = True

        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("feat1", "f1.txt", "1")

        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("feat2", "f2.txt", "2")

        self.repo_helper.checkout("feat/1")
        self.repo_helper.checkout("feat/fork", create=True)
        self.repo_helper.commit("fork", "fork.txt", "f")

        self.repo_helper.checkout("feat/1")

        ui = MockUI()

        result = execute_push_stack(
            self.repo_helper.path, target="main", ui=ui
        )
        self.assertFalse(result)

        mock_push_branches.assert_not_called()
        assert any("Fork detected downstream" in str(p) for p in ui.prints)

    def test_execute_push_stack_detached_head(self):
        # Detach head
        c = self.repo.revparse_single("main")
        self.repo.checkout_tree(c)
        self.repo.set_head(c.id)

        ui = MockUI()
        result = execute_push_stack(
            self.repo_helper.path, target="main", ui=ui
        )
        self.assertFalse(result)
        assert any("detached HEAD" in str(p) for p in ui.prints)

    @mock.patch("git_scripts.cmd.push_stack.run_cmd")
    def test_execute_push_stack_no_branches(self, mock_run_cmd):
        import typing

        import pygit2

        head_commit = typing.cast(pygit2.Commit, self.repo.head.peel())
        self.repo.create_branch("orphan", head_commit)
        self.repo_helper.checkout("orphan")
        with mock.patch(
            "git_scripts.cmd.push_stack._get_linear_stack", return_value=set()
        ):
            ui = MockUI()
            result = execute_push_stack(
                self.repo_helper.path, target="main", ui=ui
            )
            print("PRINTS NO BRANCHES:", ui.prints)
            self.assertTrue(result)
            assert any(
                "No branches found in stack" in str(p) for p in ui.prints
            )

    @mock.patch("git_scripts.cmd.push_stack.run_cmd")
    @mock.patch("git_scripts.cmd.push_stack.push_branches")
    def test_execute_push_stack_up_to_date(
        self, mock_push_branches, mock_run_cmd
    ):
        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("feat1", "f1.txt", "1")

        feat1_id = self.repo.revparse_single("feat/1").id
        self.repo.references.create("refs/remotes/origin/feat/1", feat1_id)

        ui = MockUI()
        result = execute_push_stack(
            self.repo_helper.path, target="main", ui=ui
        )

        self.assertTrue(result)
        mock_push_branches.assert_not_called()
        assert any("up-to-date with origin" in str(p) for p in ui.prints)
