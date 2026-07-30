"""Tests for the TopologyAnalyzer."""

from absl.testing import absltest

from git_scripts.git.topology import TopologyAnalyzer
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

    def test_analyzer_get_sync_point(self):
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

    def test_analyze_obsolescence(self):
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
        self.assertTrue(analysis["is_obs"])
        self.assertIsNone(analysis["cut_point"])


if __name__ == "__main__":
    absltest.main()
