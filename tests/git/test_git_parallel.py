import subprocess
from unittest.mock import MagicMock, patch

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

    def test_analyze_branches_in_parallel_weights_without_rev_list_subprocess(
        self,
    ):
        self.repo_helper.checkout("main")
        self.repo_helper.commit("base", "base.txt", "base")
        self.repo_helper.checkout("ancestor-branch", create=True)
        self.repo_helper.checkout("main")
        self.repo_helper.checkout("ahead-branch", create=True)
        self.repo_helper.commit("c1", "c1.txt", "1")
        self.repo_helper.commit("c2", "c2.txt", "2")

        on_start = MagicMock()
        progress_weights: dict[str, int] = {}

        def record_progress(branch: str, weight: int) -> None:
            progress_weights[branch] = weight

        with patch("subprocess.run", wraps=subprocess.run) as spy_run:
            result = analyze_branches_in_parallel(
                repo_path=self.repo_helper.path,
                branches=["ancestor-branch", "ahead-branch", "missing-ref"],
                target_ref="main",
                analyze_fn=lambda b: b,
                on_start=on_start,
                on_progress=record_progress,
            )

        self.assertEqual(
            result,
            {
                "ancestor-branch": "ancestor-branch",
                "ahead-branch": "ahead-branch",
                "missing-ref": "missing-ref",
            },
        )
        self.assertEqual(progress_weights["ancestor-branch"], 1)
        self.assertEqual(progress_weights["ahead-branch"], 2)
        self.assertEqual(progress_weights["missing-ref"], 1)
        on_start.assert_called_once_with(4)
        spy_run.assert_not_called()


if __name__ == "__main__":
    absltest.main()
