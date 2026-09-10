from unittest.mock import MagicMock

from absl.testing import absltest

from git_scripts.git.parallel import analyze_branches_in_parallel
from tests.helpers import GitTestRepo


class TestGitParallel(absltest.TestCase):
    def setUp(self):
        self.repo_helper = GitTestRepo()

    def tearDown(self):
        self.repo_helper.cleanup()

    def test_analyze_branches_in_parallel_calls_callbacks(self):
        self.repo_helper.commit("initial commit", "test.txt", "main")
        self.repo_helper.checkout("feature1", create=True)
        self.repo_helper.commit("commit 1", "test1.txt", "feature1")

        on_start = MagicMock()
        on_progress = MagicMock()

        def dummy_analyze(branch: str) -> str:
            return f"analyzed {branch}"

        result = analyze_branches_in_parallel(
            repo_path=self.repo_helper.path,
            branches=["feature1"],
            target_ref="main",
            analyze_fn=dummy_analyze,
            on_start=on_start,
            on_progress=on_progress,
        )

        self.assertEqual(result, {"feature1": "analyzed feature1"})

        # total_commits should be at least 1
        on_start.assert_called_once()
        self.assertGreaterEqual(on_start.call_args[0][0], 1)

        on_progress.assert_called_once()
        self.assertEqual(on_progress.call_args[0][0], "feature1")
        self.assertGreaterEqual(on_progress.call_args[0][1], 1)


if __name__ == "__main__":
    absltest.main()
