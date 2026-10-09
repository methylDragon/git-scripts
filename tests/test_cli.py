"""Unit tests for top-level CLI subcommand routing and inline help."""

# pylint: disable=missing-function-docstring

from unittest import mock

from absl.testing import absltest, parameterized
from typer.testing import CliRunner

from git_scripts.cli import app, main


class TestCli(parameterized.TestCase):
    """Verifies main() routes CLI subcommands and flags to handlers."""

    @parameterized.named_parameters(
        (
            "legacy_rebase_prefix",
            ["git-scripts", "rebase-prefix", "feat/"],
            "prefix_commands.execute_rebase_prefix",
            True,
            0,
            {"prefix": "feat/", "target": "main"},
        ),
        (
            "legacy_push_prefix_strips_all_worktrees",
            [
                "git-scripts",
                "push-prefix",
                "feat/",
                "--all-worktrees",
                "--force-with-lease",
            ],
            "prefix_commands.execute_push_prefix",
            True,
            0,
            {"prefix": "feat/", "push_opts": ["--force-with-lease"]},
        ),
        (
            "legacy_evolve",
            ["git-scripts", "evolve", "abcdef"],
            "stack_commands.execute_evolve",
            True,
            0,
            {"old_hash": "abcdef"},
        ),
        (
            "legacy_prune_local_defaults",
            ["git-scripts", "prune-local"],
            "cleanup_commands.execute_prune_local",
            True,
            0,
            {"also_prune_no_upstream": False},
        ),
        (
            "legacy_prune_local_no_upstream",
            ["git-scripts", "prune-local", "--also-prune-no-upstream"],
            "cleanup_commands.execute_prune_local",
            True,
            0,
            {"also_prune_no_upstream": True},
        ),
        (
            "legacy_prune_remote_prefix",
            ["git-scripts", "prune-remote-prefix", "feat/"],
            "cleanup_commands.execute_prune_remote_prefix",
            True,
            0,
            {"prefix": "feat/"},
        ),
        (
            "legacy_rebase_stack_target_opt_override",
            ["git-scripts", "rebase-stack", "--target", "develop"],
            "stack_commands.execute_rebase_stack",
            True,
            0,
            {"target": "develop"},
        ),
        (
            "legacy_gh_align",
            [
                "git-scripts",
                "gh-align-pr-bases-and-sync-stacks",
                "--remote",
                "upstream",
            ],
            "gh_commands.execute_align_pr_bases_and_sync_stacks",
            True,
            0,
            {"remote": "upstream", "create_missing": False},
        ),
        (
            "gh_align_subcommand_defaults",
            ["git-scripts", "gh", "align", "--remote", "upstream"],
            "gh_commands.execute_align_pr_bases_and_sync_stacks",
            True,
            0,
            {"remote": "upstream", "create_missing": False},
        ),
        (
            "gh_align_subcommand_create_missing",
            [
                "git-scripts",
                "gh",
                "align",
                "feat/",
                "main",
                "--create-missing",
            ],
            "gh_commands.execute_align_pr_bases_and_sync_stacks",
            True,
            0,
            {
                "prefix": "feat/",
                "target": "main",
                "create_missing": True,
            },
        ),
        (
            "stack_rebase_subcommand",
            ["git-scripts", "stack", "rebase", "develop"],
            "stack_commands.execute_rebase_stack",
            True,
            0,
            {"target": "develop"},
        ),
        (
            "stack_rebase_failure_exits_nonzero",
            ["git-scripts", "stack", "rebase"],
            "stack_commands.execute_rebase_stack",
            False,
            1,
            {"target": "main"},
        ),
        (
            "stack_push_subcommand_extra_opts",
            ["git-scripts", "stack", "push", "--target", "develop", "--force"],
            "stack_commands.execute_push_stack",
            True,
            0,
            {"target": "develop", "push_opts": ["--force"]},
        ),
        (
            "stack_evolve_subcommand",
            ["git-scripts", "stack", "evolve", "1234567"],
            "stack_commands.execute_evolve",
            True,
            0,
            {"old_hash": "1234567"},
        ),
        (
            "prefix_rebase_subcommand",
            ["git-scripts", "prefix", "rebase", "feat/"],
            "prefix_commands.execute_rebase_prefix",
            True,
            0,
            {"prefix": "feat/"},
        ),
        (
            "prefix_push_subcommand_extra_opts",
            ["git-scripts", "prefix", "push", "feat/", "--force-with-lease"],
            "prefix_commands.execute_push_prefix",
            True,
            0,
            {"prefix": "feat/", "push_opts": ["--force-with-lease"]},
        ),
        (
            "prefix_prune_subcommand",
            ["git-scripts", "prefix", "prune", "feat/"],
            "cleanup_commands.execute_prune_remote_prefix",
            True,
            0,
            {"prefix": "feat/"},
        ),
        (
            "cleanup_branches_local_subcommand",
            [
                "git-scripts",
                "cleanup",
                "branches",
                "local",
                "--prefix",
                "feat/",
                "--also-prune-no-upstream",
            ],
            "cleanup_commands.execute_prune_local",
            True,
            0,
            {"prefix": "feat/", "also_prune_no_upstream": True},
        ),
        (
            "cleanup_branches_remote_subcommand",
            [
                "git-scripts",
                "cleanup",
                "branches",
                "remote",
                "feat/",
                "--also-prune-no-local",
            ],
            "cleanup_commands.execute_prune_remote_prefix",
            True,
            0,
            {"prefix": "feat/", "also_prune_no_local": True},
        ),
        (
            "gk_watch_daemon_subcommand",
            [
                "git-scripts",
                "gk",
                "watch-daemon",
                "/tmp/repo/.git",
                "--gk-pid",
                "42",
            ],
            "gk_commands.execute_watch_daemon",
            True,
            0,
            {"gk_pid": 42},
        ),
    )
    def test_main_routes_subcommand_and_propagates_exit_code(
        self, argv, target_fn, return_value, expected_code, expected_kwargs
    ):
        with (
            mock.patch("sys.argv", argv),
            mock.patch(f"git_scripts.cli.{target_fn}") as mock_exec,
        ):
            mock_exec.return_value = return_value
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, expected_code)
            mock_exec.assert_called_once()
            for key, val in expected_kwargs.items():
                self.assertEqual(mock_exec.call_args.kwargs[key], val)

    @parameterized.named_parameters(
        (
            "legacy_gk_optimize_install",
            [
                "git-scripts",
                "gk-optimize",
                "install",
                "--keep-recent-tags",
                "5",
            ],
            "execute_gk_install",
            "success",
            {"keep_recent_override": 5},
        ),
        (
            "gk_install_subcommand",
            ["git-scripts", "gk", "install", "--keep-recent-tags", "3"],
            "execute_gk_install",
            "success",
            {"keep_recent_override": 3},
        ),
        (
            "gk_verify_subcommand",
            ["git-scripts", "gk", "verify", "--expect", "uninstalled"],
            "execute_gk_verify",
            "passed",
            {},
        ),
        (
            "gk_uninstall_subcommand",
            ["git-scripts", "gk", "uninstall", "--close-gitkraken"],
            "execute_gk_uninstall",
            "success",
            {"close_gitkraken": True},
        ),
    )
    def test_main_routes_gk_result_subcommands(
        self, argv, target_fn, result_attr, expected_kwargs
    ):
        with (
            mock.patch("sys.argv", argv),
            mock.patch(
                f"git_scripts.cli.gk_commands.{target_fn}"
            ) as mock_exec,
        ):
            setattr(mock_exec.return_value, result_attr, True)
            with self.assertRaises(SystemExit) as ctx:
                main()
            self.assertEqual(ctx.exception.code, 0)
            mock_exec.assert_called_once()
            for key, val in expected_kwargs.items():
                self.assertEqual(mock_exec.call_args.kwargs[key], val)

    def test_prefix_short_help_flag_renders_git_usage_and_examples(self):
        runner = CliRunner()
        result = runner.invoke(app, ["prefix", "-h"], prog_name="git")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage: git prefix", result.output)
        self.assertIn("git prefix rebase <prefix> [target]", result.output)
        self.assertIn("Examples:", result.output)

    @parameterized.named_parameters(
        ("prefix_rebase", ["prefix", "rebase"], "Usage: git prefix rebase"),
        ("prefix_push", ["prefix", "push"], "Usage: git prefix push"),
        ("prefix_prune", ["prefix", "prune"], "Usage: git prefix prune"),
        (
            "cleanup_remote",
            ["cleanup", "branches", "remote"],
            "Usage: git cleanup branches remote",
        ),
    )
    def test_no_args_renders_help_with_usage_and_examples(
        self, args, expected_usage
    ):
        runner = CliRunner()
        result = runner.invoke(app, args, prog_name="git")
        self.assertIn(result.exit_code, (0, 2))
        self.assertIn(expected_usage, result.output)
        self.assertIn("Examples:", result.output)


if __name__ == "__main__":
    absltest.main()
