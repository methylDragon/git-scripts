from absl.testing import absltest

# Assuming we rename analysis.py to git/reads.py
from git_scripts.git.reads import (
    find_cut_point,
    find_sync_point,
    find_tips,
    format_stack_tree,
    is_obsolete,
)
from tests.helpers import GitTestRepo, run_git


class TestGitReads(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()
        self.repo = self.repo_helper.get_pygit2_repo()

    def tearDown(self):
        self.repo_helper.cleanup()

    def test_find_tips_returns_only_branches_without_children(self):
        branches = [
            "test-chain-a",
            "test-chain-a-b",
            "test-chain-a-b-c",
            "test-chain-d",
            "test-chain-d-e",
            "test-chain-d-e-f",
            "test-chain-d-e-f-g",
            "test-chain-d-e-f-g-h",
            "test-chain-d-e-f-g-h-i",
            "test-chain-d-e-f-j",
            "test-chain-d-e-f-j-k",
            "test-chain-d-e-f-j-k-l",
        ]
        tips = find_tips(self.repo, branches)
        self.assertEqual(
            sorted(tips),
            sorted(
                [
                    "test-chain-a-b-c",
                    "test-chain-d-e-f-g-h-i",
                    "test-chain-d-e-f-j-k-l",
                ]
            ),
        )

    def test_is_obsolete_returns_true_for_fast_forward_merge(self):
        # A branch that points to exactly the same tree as main
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("feature/redundant", create=True)
        # We don't commit, so it's exactly main
        commit = self.repo.revparse_single("feature/redundant")
        self.assertTrue(is_obsolete(self.repo, commit.id, "main"))

    def test_is_obsolete_returns_true_for_cherry_picked_commits(self):
        # Create a commit on a branch
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("feature/cherry", create=True)
        self.repo_helper.commit("cherry commit", "cherry.txt", "cherry")
        cherry_commit_hash = self.repo.revparse_single("feature/cherry").id

        # Cherry pick to main
        self.repo_helper.checkout("main")

        # We must actually cherry-pick it using Git so the patch-ids strictly
        # match
        run_git(["cherry-pick", "feature/cherry"], cwd=self.repo_helper.path)

        # Now feature/cherry should be obsolete (Patch-ID match)
        self.assertTrue(is_obsolete(self.repo, cherry_commit_hash, "main"))

    def test_is_obsolete_returns_true_for_squash_merge(self):
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("feature/squash", create=True)
        self.repo_helper.commit("c1", "file1.txt", "1")
        self.repo_helper.commit("c2", "file2.txt", "2")
        squash_commit_hash = self.repo.revparse_single("feature/squash").id

        self.repo_helper.checkout("main")
        run_git(
            ["merge", "--squash", "feature/squash"], cwd=self.repo_helper.path
        )
        self.repo_helper.commit("squashed c1 and c2", "none.txt", "none")

        self.assertTrue(is_obsolete(self.repo, squash_commit_hash, "main"))

    def test_find_cut_point_returns_latest_merged_ancestor(self):
        # main-base -> test-chain-a -> test-chain-a-b -> test-chain-a-b-c
        # If test-chain-a is merged to main, cut point is a.
        self.repo_helper.checkout("main")
        self.repo_helper.commit("merge a", "a.txt", "a")

        # We simulate that 'test-chain-a' content was merged into main.
        # So finding cut point for test-chain-a-b-c finds test-chain-a.
        # We'll just test a simpler linear stack.
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("1", "1.txt", "1")
        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("2", "2.txt", "2")

        feat_1_hash = self.repo.revparse_single("feat/1").id

        # Merge feat/1 into main
        self.repo_helper.checkout("main")
        self.repo_helper.commit(
            "1 on main", "1.txt", "1"
        )  # Identical content (patch match); diff msg avoids collision

        cut_point = find_cut_point(
            self.repo, str(self.repo.revparse_single("feat/2").id), "main"
        )
        self.assertEqual(cut_point, str(feat_1_hash))

    def test_find_sync_point_returns_closest_moved_ancestor(self):
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("A", create=True)
        self.repo_helper.commit("A", "a.txt", "a")
        a_initial = str(self.repo.revparse_single("A").id)

        self.repo_helper.checkout("B", create=True)
        self.repo_helper.commit("B", "b.txt", "b")
        b_initial = str(self.repo.revparse_single("B").id)

        self.repo_helper.checkout("C", create=True)
        self.repo_helper.commit("C", "c.txt", "c")
        c_initial = str(self.repo.revparse_single("C").id)

        initial_map = {"A": a_initial, "B": b_initial, "C": c_initial}
        all_branches = ["A", "B", "C"]

        # Simulate rebase by moving B
        self.repo_helper.checkout("B")
        self.repo_helper.commit("B rebased", "b2.txt", "b2")
        b_new = str(self.repo.revparse_single("B").id)

        sync_point = find_sync_point(self.repo, "C", all_branches, initial_map)
        self.assertIsNotNone(sync_point)
        self.assertEqual(sync_point, ("B", b_initial, b_new))

    def test_format_stack_tree_outputs_correct_hierarchy(self):
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("A", create=True)
        self.repo_helper.commit("A", "a.txt", "a")

        self.repo_helper.checkout("B", create=True)
        self.repo_helper.commit("B", "b.txt", "b")

        self.repo_helper.checkout("C", create=True)
        self.repo_helper.commit("C", "c.txt", "c")

        tree = format_stack_tree(self.repo, "C", allowed_refs={"A", "B", "C"})
        expected = """
C
    ├─ B
    └─ A
""".strip()
        self.assertEqual(tree, expected)


if __name__ == "__main__":
    absltest.main()
