"""Unit tests for top-level CLI subcommand routing."""

# pylint: disable=missing-function-docstring

from unittest import mock

from absl.testing import absltest

from git_scripts.cli import main


class TestCli(absltest.TestCase):
    """Verifies main() routes CLI subcommands to their execution handlers."""

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
        self.assertFalse(mock_exec.call_args.kwargs["also_prune_no_upstream"])

    @mock.patch(
        "sys.argv",
        ["git-scripts", "prune-local", "--also-prune-no-upstream"],
    )
    @mock.patch("git_scripts.cli.execute_prune_local")
    def test_main_routes_to_prune_local_with_no_upstream_flag_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertTrue(mock_exec.call_args.kwargs["also_prune_no_upstream"])

    @mock.patch("sys.argv", ["git-scripts", "prune-remote-prefix", "feat/"])
    @mock.patch("git_scripts.cli.execute_prune_remote_prefix")
    def test_main_routes_to_prune_remote_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()

    @mock.patch("sys.argv", ["git-scripts", "rebase-stack"])
    @mock.patch("git_scripts.cli.execute_rebase_stack")
    def test_main_routes_to_rebase_stack_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()

    @mock.patch(
        "sys.argv",
        ["git-scripts", "gk-optimize", "install", "--keep-recent-tags", "5"],
    )
    @mock.patch("git_scripts.cli.execute_gk_install")
    def test_main_routes_to_gk_optimize_install_when_invoked(self, mock_exec):
        mock_exec.return_value = mock.MagicMock(success=True)
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["keep_recent_override"], 5)

    @mock.patch(
        "sys.argv",
        [
            "git-scripts",
            "gh",
            "align",
            "--remote",
            "upstream",
        ],
    )
    @mock.patch("git_scripts.cli.execute_align_pr_bases_and_sync_stacks")
    def test_main_routes_to_gh_align_subcommand_when_invoked(self, mock_exec):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["remote"], "upstream")

    @mock.patch(
        "sys.argv",
        [
            "git-scripts",
            "gh-align-pr-bases-and-sync-stacks",
            "--remote",
            "upstream",
        ],
    )
    @mock.patch("git_scripts.cli.execute_align_pr_bases_and_sync_stacks")
    def test_main_routes_to_gh_align_pr_bases_with_remote_flag_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["remote"], "upstream")

    @mock.patch("sys.argv", ["git-scripts", "stack", "rebase", "develop"])
    @mock.patch("git_scripts.cli.execute_rebase_stack")
    def test_main_routes_to_stack_rebase_subcommand_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["target"], "develop")

    @mock.patch(
        "sys.argv",
        ["git-scripts", "stack", "push", "--target", "develop", "--force"],
    )
    @mock.patch("git_scripts.cli.execute_push_stack")
    def test_main_routes_to_stack_push_subcommand_with_extra_opts(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["target"], "develop")
        self.assertEqual(mock_exec.call_args.kwargs["push_opts"], ["--force"])

    @mock.patch("sys.argv", ["git-scripts", "stack", "evolve", "1234567"])
    @mock.patch("git_scripts.cli.execute_evolve")
    def test_main_routes_to_stack_evolve_subcommand_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["old_hash"], "1234567")

    @mock.patch("sys.argv", ["git-scripts", "prefix", "rebase", "feat/"])
    @mock.patch("git_scripts.cli.execute_rebase_prefix")
    def test_main_routes_to_prefix_rebase_subcommand_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["prefix"], "feat/")

    @mock.patch(
        "sys.argv",
        ["git-scripts", "prefix", "push", "feat/", "--force-with-lease"],
    )
    @mock.patch("git_scripts.cli.execute_push_prefix")
    def test_main_routes_to_prefix_push_subcommand_with_extra_opts(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["prefix"], "feat/")
        self.assertEqual(
            mock_exec.call_args.kwargs["push_opts"], ["--force-with-lease"]
        )

    @mock.patch("sys.argv", ["git-scripts", "prefix", "prune", "feat/"])
    @mock.patch("git_scripts.cli.execute_prune_remote_prefix")
    def test_main_routes_to_prefix_prune_subcommand_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["prefix"], "feat/")

    @mock.patch(
        "sys.argv",
        [
            "git-scripts",
            "cleanup",
            "branches",
            "local",
            "--prefix",
            "feat/",
            "--also-prune-no-upstream",
        ],
    )
    @mock.patch("git_scripts.cli.execute_prune_local")
    def test_main_routes_to_cleanup_branches_local_with_prefix_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["prefix"], "feat/")
        self.assertTrue(mock_exec.call_args.kwargs["also_prune_no_upstream"])

    @mock.patch(
        "sys.argv",
        [
            "git-scripts",
            "cleanup",
            "branches",
            "remote",
            "feat/",
            "--also-prune-no-local",
        ],
    )
    @mock.patch("git_scripts.cli.execute_prune_remote_prefix")
    def test_main_routes_to_cleanup_branches_remote_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = True
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["prefix"], "feat/")
        self.assertTrue(mock_exec.call_args.kwargs["also_prune_no_local"])

    @mock.patch(
        "sys.argv",
        ["git-scripts", "gk", "install", "--keep-recent-tags", "3"],
    )
    @mock.patch("git_scripts.cli.execute_gk_install")
    def test_main_routes_to_gk_install_subcommand_when_invoked(
        self, mock_exec
    ):
        mock_exec.return_value = mock.MagicMock(success=True)
        try:
            main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        mock_exec.assert_called_once()
        self.assertEqual(mock_exec.call_args.kwargs["keep_recent_override"], 3)
