import subprocess
from unittest.mock import patch

from absl.testing import absltest

from git_scripts.git.core import GitExecutionError, run_cmd


class TestGitCore(absltest.TestCase):
    @patch("git_scripts.git.core.subprocess.run")
    def test_run_cmd_returns_stripped_stdout_when_command_succeeds(
        self, mock_run
    ):
        mock_run.return_value.stdout = "output\n"
        result = run_cmd(["git", "status"])
        self.assertEqual(result, "output")
        mock_run.assert_called_once_with(
            ["git", "status"],
            cwd=None,
            check=True,
            capture_output=True,
            text=True,
        )

    @patch("git_scripts.git.core.subprocess.run")
    def test_run_cmd_raises_git_execution_error_with_stderr_when_command_fails(
        self, mock_run
    ):
        error = subprocess.CalledProcessError(1, ["git", "status"])
        error.stderr = "fatal error"
        mock_run.side_effect = error

        with self.assertRaises(GitExecutionError) as cm:
            run_cmd(["git", "status"])

        self.assertIn("Command failed: git status", str(cm.exception))
        self.assertIn("Error: fatal error", str(cm.exception))


if __name__ == "__main__":
    absltest.main()
