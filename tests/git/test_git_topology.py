"""Tests for the TopologyAnalyzer."""

from unittest.mock import MagicMock, patch

from absl.testing import absltest

from git_scripts.git.topology import (
    TopologyAnalyzer,
    check_remote_push_parity,
    find_linear_stack,
    sort_branches_bottom_to_top,
)
from tests.helpers import GitTestRepo


class TestTopologyAnalyzer(absltest.TestCase):
    """Tests the TopologyAnalyzer class."""

    def setUp(self):  # pylint: disable=invalid-name
        """Sets up the test repo."""
        self.repo_helper = GitTestRepo()
        self.repo = self.repo_helper.get_pygit2_repo()

    def tearDown(self):  # pylint: disable=invalid-name
        """Cleans up the test repo."""
        self.repo_helper.cleanup()

    def test_analyzer_initializes_and_finds_tips(self):
        """Tests that the analyzer finds branch tips correctly."""
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("A", create=True)
        self.repo_helper.commit("A", "a.txt", "a")

        self.repo_helper.checkout("B", create=True)
        self.repo_helper.commit("B", "b.txt", "b")

        self.repo_helper.checkout("C", create=True)
        self.repo_helper.commit("C", "c.txt", "c")

        analyzer = TopologyAnalyzer(self.repo_helper.path, ["A", "B", "C"])

        self.assertEqual(len(analyzer.initial_ref_map), 3)
        self.assertEqual(analyzer.tips, ["C"])

    def test_analyze_obsolescence_calls_callback(self):
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("A", create=True)
        self.repo_helper.commit("A", "a.txt", "a")

        mock_progress = MagicMock()
        analyzer = TopologyAnalyzer(self.repo_helper.path, ["A"])
        analyzer.analyze_obsolescence("main", progress_callback=mock_progress)
        self.assertGreaterEqual(mock_progress.call_count, 1)

    def test_get_sync_point_returns_old_and_new_hashes_after_parent_rebases(
        self,
    ):
        """Tests that the analyzer finds sync points correctly."""
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("A", create=True)
        self.repo_helper.commit("A", "a.txt", "a")

        self.repo_helper.checkout("B", create=True)
        self.repo_helper.commit("B", "b.txt", "b")

        self.repo_helper.checkout("C", create=True)
        self.repo_helper.commit("C", "c.txt", "c")

        # Initialize analyzer before moving B
        analyzer = TopologyAnalyzer(self.repo_helper.path, ["A", "B", "C"])

        # Move B
        self.repo_helper.checkout("B")
        self.repo_helper.commit("B rebased", "b2.txt", "b2")
        b_new = str(self.repo.revparse_single("B").id)
        b_old = analyzer.initial_ref_map["B"]

        sync_point = analyzer.get_sync_point("C")
        self.assertIsNotNone(sync_point)
        self.assertEqual(sync_point, ("B", b_old, b_new))

    def test_analyze_obsolescence_marks_merged_branch_obsolete(
        self,
    ):
        """Tests analyzing branch topology and obsolescence caching."""
        self.repo_helper.checkout("main")
        self.repo_helper.commit("init", "init.txt", "init")

        self.repo_helper.checkout("feat", create=True)
        self.repo_helper.commit("feat on branch", "feat.txt", "feat")

        # Merge feat into main identically (simulating squash/fast-forward)
        # Message differs to prevent timestamp-based hash collisions
        self.repo_helper.checkout("main")
        self.repo_helper.commit("feat on main", "feat.txt", "feat")

        analyzer = TopologyAnalyzer(self.repo_helper.path, ["feat"])
        analyzer.analyze_obsolescence("main")

        analysis = analyzer.get_analysis("feat")
        self.assertTrue(analysis.is_obsolete)
        self.assertIsNone(analysis.cut_point)

    def test_find_linear_stack_collects_all_ancestors_up_to_root(self):
        """Tests finding a linear stack."""
        repo = MagicMock()
        with patch(
            "git_scripts.git.topology.get_parent_branch",
            side_effect=["b1", "b2", None],
        ):
            self.assertEqual(
                find_linear_stack(repo, "start", {"b1", "b2", "start"}),
                {"start", "b1", "b2"},
            )

    def test_find_linear_stack_excludes_branch_colocated_with_target(self):
        """Excludes unrelated branches parked on the same commit as target."""
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("aaa-parked-on-main", create=True)

        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("feat 1", "f1.txt", "1")

        self.repo_helper.checkout("feat/2", create=True)
        self.repo_helper.commit("feat 2", "f2.txt", "2")

        pool = {"main", "aaa-parked-on-main", "feat/1", "feat/2"}
        stack = find_linear_stack(self.repo, "feat/2", pool, stop_at="main")
        self.assertEqual(stack, {"feat/1", "feat/2"})

    def test_find_linear_stack_stops_downward_walk_when_fork_is_detected(self):
        """Does not arbitrarily include forked descendant branches."""
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("feat/1", create=True)
        self.repo_helper.commit("feat 1", "f1.txt", "1")

        self.repo_helper.checkout("feat/2a", create=True)
        self.repo_helper.commit("feat 2a", "f2a.txt", "2a")

        self.repo_helper.checkout("feat/1")
        self.repo_helper.checkout("feat/2b", create=True)
        self.repo_helper.commit("feat 2b", "f2b.txt", "2b")

        pool = {"main", "feat/1", "feat/2a", "feat/2b"}
        stack = find_linear_stack(self.repo, "feat/1", pool, stop_at="main")
        self.assertEqual(stack, {"feat/1"})

    def test_check_remote_push_parity_classifies_branch_states(self):
        """Classifies synced, unpushed, diverged, and behind branches."""
        self.repo_helper.checkout("main")
        main_id = self.repo.revparse_single("main").id

        # 1. synced
        self.repo_helper.checkout("b-synced", create=True)
        self.repo_helper.commit("synced", "s.txt", "s")
        synced_id = self.repo.revparse_single("b-synced").id
        self.repo.references.create("refs/remotes/origin/b-synced", synced_id)

        # 2. unpushed (no remote ref)
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("b-new", create=True)
        self.repo_helper.commit("new", "n.txt", "n")

        # 3. unpushed-ahead (fast-forwardable ahead of origin)
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("b-ahead", create=True)
        self.repo_helper.commit("ahead", "a.txt", "a")
        self.repo.references.create("refs/remotes/origin/b-ahead", main_id)

        # 4. diverged (local and remote have diverged commits)
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("b-diverged-remote", create=True)
        self.repo_helper.commit("remote commit", "dr.txt", "dr")
        diverged_remote_id = self.repo.revparse_single("b-diverged-remote").id
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("b-diverged", create=True)
        self.repo_helper.commit("local rebased", "dl.txt", "dl")
        self.repo.references.create(
            "refs/remotes/origin/b-diverged", diverged_remote_id
        )

        # 5. behind (remote is strictly ahead of local)
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("b-behind", create=True)
        self.repo_helper.commit("base commit", "bb1.txt", "bb1")
        behind_local_id = self.repo.revparse_single("b-behind").id
        self.repo_helper.commit("remote-only commit", "bb2.txt", "bb2")
        behind_remote_id = self.repo.revparse_single("b-behind").id
        self.repo.references.create(
            "refs/heads/b-behind", behind_local_id, force=True
        )
        self.repo.references.create(
            "refs/remotes/origin/b-behind", behind_remote_id
        )

        parity = check_remote_push_parity(
            self.repo,
            ["b-synced", "b-new", "b-ahead", "b-diverged", "b-behind"],
        )
        self.assertFalse(parity.is_synced)
        self.assertEqual(
            parity.unpushed_branches, ("b-new", "b-ahead", "b-diverged")
        )
        self.assertEqual(parity.diverged_branches, ("b-diverged",))
        self.assertEqual(parity.behind_remote_branches, ("b-behind",))

    def test_check_remote_push_parity_checks_specified_remote_refs(self):
        """Verifies push parity against a non-origin remote."""
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("b-up", create=True)
        self.repo_helper.commit("up", "u.txt", "u")
        up_id = self.repo.revparse_single("b-up").id
        self.repo.references.create("refs/remotes/upstream/b-up", up_id)

        origin_parity = check_remote_push_parity(
            self.repo, ["b-up"], remote="origin"
        )
        self.assertEqual(origin_parity.unpushed_branches, ("b-up",))

        upstream_parity = check_remote_push_parity(
            self.repo, ["b-up"], remote="upstream"
        )
        self.assertTrue(upstream_parity.is_synced)

    def test_sort_branches_bottom_to_top_orders_parents_before_children(self):
        """Tests sorting branches."""
        parent_map: dict[str, str | None] = {
            "b1": "main",
            "b2": "b1",
            "b3": "b2",
        }
        ordered = sort_branches_bottom_to_top({"b1", "b2", "b3"}, parent_map)
        self.assertEqual(ordered, ["b1", "b2", "b3"])


if __name__ == "__main__":
    absltest.main()
