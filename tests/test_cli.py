from unittest import mock

from absl.testing import absltest

from git_scripts.cli import main


class TestCli(absltest.TestCase):
    @mock.patch("sys.argv", ["git-scripts", "rebase-prefix", "feat/"])
    @mock.patch("git_scripts.cli.execute_rebase_prefix")
    def test_main_routes_to_rebase_prefix_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()

    @mock.patch("sys.argv", ["git-scripts", "push-prefix", "feat/"])
    @mock.patch("git_scripts.cli.execute_push_prefix")
    def test_main_routes_to_push_prefix_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()

    @mock.patch("sys.argv", ["git-scripts", "evolve", "abcdef"])
    @mock.patch("git_scripts.cli.execute_evolve")
    def test_main_routes_to_evolve_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()

    @mock.patch("sys.argv", ["git-scripts", "prune-local"])
    @mock.patch("git_scripts.cli.execute_prune_local")
    def test_main_routes_to_prune_local_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()

    @mock.patch("sys.argv", ["git-scripts", "prune-remote", "feat/"])
    @mock.patch("git_scripts.cli.execute_prune_remote")
    def test_main_routes_to_prune_remote_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
