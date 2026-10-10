from unittest import mock

from absl.testing import absltest

from git_scripts.cmd.rebase.rebase_prefix import execute_rebase_prefix
from git_scripts.ui import UI
from tests.helpers import GitTestRepo, run_git


class TestCmdRebasePrefix(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()

    def tearDown(self):
        self.repo_helper.cleanup()

    @mock.patch("git_scripts.cmd.rebase.rebase_orchestrator.push_branches")
    def test_execute_rebase_prefix_rebases_linear_and_forking_chains(
        self, mock_push
    ):
        self.repo_helper.checkout("main")
        self.repo_helper.commit("main-update")

        # Act
        ui = UI(auto_yes=True)

        # Verify it restores to the initially checked-out branch
        self.repo_helper.checkout("test-chain-a")

        # Hook the mock to verify branch is restored BEFORE push prompts
        def verify_restored(*args, **kwargs):
            current_branch = self.repo_helper.get_pygit2_repo().head.shorthand
            self.assertEqual(current_branch, "test-chain-a")

        mock_push.side_effect = verify_restored

        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="test-chain-",
            target="main",
            all_worktrees=False,
            auto_delete=False,  # Keep merged branches to assert on them
            ui=ui,
        )
        self.assertTrue(success)

        # Check that mock was called
        mock_push.assert_called_once()

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

    @mock.patch("git_scripts.cmd.rebase.rebase_orchestrator.push_branches")
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

    @mock.patch("git_scripts.cmd.rebase.rebase_orchestrator.push_branches")
    def test_execute_rebase_prefix_rebases_clean_stacks_before_conflict_pass(
        self, mock_push
    ):
        self.repo_helper.checkout("main")
        self.repo_helper.commit(
            "conflict on main", "shared_conflict.txt", "from-main"
        )

        # Create an independent clean stack alongside a conflicted stack.
        self.repo_helper.checkout("main~1")
        self.repo_helper.checkout("two-pass/1-conflict", create=True)
        self.repo_helper.commit(
            "branch 1 conflict", "shared_conflict.txt", "branch-1"
        )

        self.repo_helper.checkout("main~1")
        self.repo_helper.checkout("two-pass/2-clean", create=True)
        self.repo_helper.commit("branch 2 clean", "clean_2.txt", "clean-2")

        self.repo_helper.checkout("main")
        main_hash = self.repo_helper.rev_parse("main")

        ui = mock.MagicMock(spec=UI)
        ui.auto_yes = True
        ui.plain = True
        ui.console = UI(plain=True, auto_yes=True).console
        ui.pluralize.side_effect = UI(plain=True, auto_yes=True).pluralize

        clean_rebased_before_prompt = []

        def on_ask_choice(msg, choices, default=None):
            if "How would you like to handle this?" in msg:
                # At the moment Pass 2 prompts for two-pass/1-conflict,
                # two-pass/2-clean MUST already be rebased onto main!
                clean_parent = self.repo_helper.rev_parse("two-pass/2-clean~1")
                clean_rebased_before_prompt.append(clean_parent == main_hash)
                return "Resolve manually, then continue"
            return default or choices[0]

        def on_pause(msg=""):
            # Resolve the conflict in shared_conflict.txt during Pass 2 pause
            conflict_file = f"{self.repo_helper.path}/shared_conflict.txt"
            with open(conflict_file, "w", encoding="utf-8") as f:
                f.write("resolved-content\n")
            run_git(["add", "shared_conflict.txt"], cwd=self.repo_helper.path)

        ui.ask_choice.side_effect = on_ask_choice
        ui.pause.side_effect = on_pause

        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="two-pass/",
            target="main",
            all_worktrees=False,
            auto_delete=False,
            ui=ui,
        )

        self.assertTrue(success)
        self.assertEqual(clean_rebased_before_prompt, [True])
        self._assert_parent("main", "two-pass/2-clean")
        self._assert_parent("main", "two-pass/1-conflict")

    @mock.patch("git_scripts.cmd.rebase.rebase_orchestrator.push_branches")
    def test_execute_rebase_prefix_resolves_shared_fork_stem_conflict_once(
        self, mock_push
    ):
        # main
        #  └─ fork-test/stem (conflicts with new main)
        #      ├─ fork-test/branch-1
        #      └─ fork-test/branch-2
        self.repo_helper.checkout("main")
        self.repo_helper.commit("base", "fork_conflict.txt", "base")

        self.repo_helper.checkout("fork-test/stem", create=True)
        self.repo_helper.commit(
            "stem change", "fork_conflict.txt", "stem-side"
        )

        self.repo_helper.checkout("fork-test/branch-1", create=True)
        self.repo_helper.commit("b1 change", "b1.txt", "b1")

        self.repo_helper.checkout("fork-test/stem")
        self.repo_helper.checkout("fork-test/branch-2", create=True)
        self.repo_helper.commit("b2 change", "b2.txt", "b2")

        self.repo_helper.checkout("main")
        self.repo_helper.commit(
            "main conflicting change", "fork_conflict.txt", "main-side"
        )

        ui = mock.MagicMock(spec=UI)
        ui.auto_yes = True
        ui.plain = True
        ui.console = UI(plain=True, auto_yes=True).console
        ui.pluralize.side_effect = UI(plain=True, auto_yes=True).pluralize

        conflict_prompts = []

        def on_ask_choice(msg, choices, default=None):
            if "How would you like to handle this?" in msg:
                conflict_prompts.append(msg)
                return "Resolve manually, then continue"
            return default or choices[0]

        def on_pause(msg=""):
            conflict_file = f"{self.repo_helper.path}/fork_conflict.txt"
            with open(conflict_file, "w", encoding="utf-8") as f:
                f.write("merged-stem-and-main\n")
            run_git(["add", "fork_conflict.txt"], cwd=self.repo_helper.path)

        ui.ask_choice.side_effect = on_ask_choice
        ui.pause.side_effect = on_pause

        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="fork-test/",
            target="main",
            all_worktrees=False,
            auto_delete=False,
            ui=ui,
        )

        self.assertTrue(success)
        # The shared stem conflict is prompted only ONCE in Pass 2; the second
        # fork branch dynamically syncs onto the resolved stem.
        self.assertEqual(len(conflict_prompts), 1)
        self._assert_parent("main", "fork-test/stem")
        self._assert_parent("fork-test/stem", "fork-test/branch-1")
        self._assert_parent("fork-test/stem", "fork-test/branch-2")

    @mock.patch("git_scripts.cmd.rebase.rebase_orchestrator.push_branches")
    def test_execute_rebase_prefix_deletes_selected_merged_branch_in_worktree(
        self, mock_push
    ):
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("ch3/insrc-iii", create=True)
        self.repo_helper.commit("insrc-iii", "insrc.txt", "insrc")
        insrc_id = (
            self.repo_helper.get_pygit2_repo().revparse_single("HEAD").id
        )

        self.repo_helper.checkout("main")
        self.repo_helper.checkout("ch3/quota-service-owners", create=True)
        self.repo_helper.commit("quota-owners", "quota.txt", "quota")

        self.repo_helper.checkout("main")
        self.repo_helper.commit("insrc squashed", "insrc.txt", "insrc")
        self.repo_helper.commit("quota squashed", "quota.txt", "quota")

        self.repo_helper.checkout("ch3/active-branch", create=True)
        self.repo_helper.commit("active work", "active.txt", "active")

        wt_quota = f"{self.repo_helper.temp_dir.name}/wt_quota"
        self.repo_helper.create_worktree(wt_quota, "ch3/quota-service-owners")

        ui = mock.MagicMock(spec=UI)
        ui.auto_yes = False
        ui.plain = True
        ui.console = UI(plain=True, auto_yes=False).console
        ui.pluralize.side_effect = UI(plain=True, auto_yes=False).pluralize

        def on_ask_choice(msg, choices, default=None):
            del choices
            if "Delete the 2 fully merged local branches?" in msg:
                return "Select which to delete"
            if "Push" in msg:
                return "Skip all"
            return default

        ui.ask_choice.side_effect = on_ask_choice
        ui.ask_checkbox.return_value = ["ch3/quota-service-owners"]

        success = execute_rebase_prefix(
            repo_path=self.repo_helper.path,
            prefix="ch3/",
            target="main",
            all_worktrees=True,
            auto_delete=False,
            ui=ui,
        )

        self.assertTrue(success)
        mock_push.assert_not_called()
        local_branches = set(self.repo_helper.get_pygit2_repo().branches.local)
        self.assertNotIn("ch3/quota-service-owners", local_branches)
        self.assertIn("ch3/insrc-iii", local_branches)
        self.assertEqual(
            self.repo_helper.get_pygit2_repo()
            .revparse_single("ch3/insrc-iii")
            .id,
            insrc_id,
        )

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
