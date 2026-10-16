"""Unit tests for top-level CLI subcommand routing and inline help."""

# pylint: disable=missing-function-docstring

import re
from unittest import mock

from absl.testing import absltest, parameterized
from typer.testing import CliRunner

from git_scripts.cli import app, main

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class TestCli(parameterized.TestCase):
    """Verifies main() routes CLI subcommands and flags to handlers."""

    @parameterized.named_parameters(
        (
            "evolve_root_command",
            ["git-scripts", "evolve", "abcdef"],
            "execute_evolve",
            True,
            0,
            {"old_hash": "abcdef"},
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
                "develop",
                "--prefix",
                "feat/",
                "-c",
                "--create-missing",
            ],
            "gh_commands.execute_align_pr_bases_and_sync_stacks",
            True,
            0,
            {
                "prefix": "feat/",
                "target": "develop",
                "current_stack_only": True,
                "create_missing": True,
            },
        ),
        (
            "batch_rebase_defaults_to_current_stack",
            ["git-scripts", "batch", "rebase", "develop", "--dry-run"],
            "batch_commands.execute_rebase_stack",
            True,
            0,
            {"target": "develop", "dry_run": True},
        ),
        (
            "batch_rebase_failure_exits_nonzero",
            ["git-scripts", "batch", "rebase", "--current"],
            "batch_commands.execute_rebase_stack",
            False,
            1,
            {"target": "main", "dry_run": False},
        ),
        (
            "batch_rebase_prefix_option",
            [
                "git-scripts",
                "batch",
                "rebase",
                "develop",
                "--prefix",
                "feat/",
                "--all-worktrees",
            ],
            "batch_commands.execute_rebase_prefix",
            True,
            0,
            {"prefix": "feat/", "target": "develop", "all_worktrees": True},
        ),
        (
            "batch_push_defaults_to_current_stack",
            ["git-scripts", "batch", "push", "--target", "develop", "--force"],
            "batch_commands.execute_push_stack",
            True,
            0,
            {"target": "develop", "push_opts": ["--force"]},
        ),
        (
            "batch_push_prefix_option_with_dry_run",
            [
                "git-scripts",
                "batch",
                "push",
                "-p",
                "feat/",
                "--dry-run",
                "--force-with-lease",
            ],
            "batch_commands.execute_push_prefix",
            True,
            0,
            {
                "prefix": "feat/",
                "push_opts": ["--force-with-lease", "--dry-run"],
            },
        ),
        (
            "batch_prune_local_subcommand",
            [
                "git-scripts",
                "batch",
                "prune",
                "local",
                "develop",
                "-p",
                "feat/",
                "--also-prune-no-upstream",
            ],
            "batch_commands.execute_prune_local",
            True,
            0,
            {
                "target": "develop",
                "prefix": "feat/",
                "also_prune_no_upstream": True,
            },
        ),
        (
            "batch_prune_remote_prefix_option",
            [
                "git-scripts",
                "batch",
                "prune",
                "remote",
                "develop",
                "-p",
                "feat/",
                "--also-prune-no-local",
            ],
            "batch_commands.execute_prune_remote_prefix",
            True,
            0,
            {
                "prefix": "feat/",
                "target": "develop",
                "also_prune_no_local": True,
            },
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

    def test_batch_short_help_flag_renders_git_usage_and_examples(self):
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["batch", "-h"],
            prog_name="git",
            env={"FORCE_COLOR": "1", "TERM": "xterm-256color"},
        )
        output = _strip_ansi(result.output)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage: git batch", output)
        self.assertIn("git batch rebase main --prefix feat/", output)
        self.assertIn("Examples:", output)

    @parameterized.named_parameters(
        (
            "batch_rebase_conflict",
            ["batch", "rebase", "--current", "--prefix", "feat/"],
            "Cannot combine --current (-c) and --prefix (-p)",
        ),
        (
            "batch_push_conflict",
            ["batch", "push", "-c", "-p", "feat/"],
            "Cannot combine --current (-c) and --prefix (-p)",
        ),
        (
            "batch_prune_remote_missing_prefix",
            ["batch", "prune", "remote"],
            "Missing branch prefix. Pass --prefix (-p) <pfx>",
        ),
    )
    def test_batch_invalid_flag_combinations_fail_with_recovery_hint(
        self, args, expected_error
    ):
        runner = CliRunner()
        result = runner.invoke(app, args, prog_name="git")
        output = _strip_ansi(result.output)
        self.assertEqual(result.exit_code, 2)
        self.assertIn(expected_error, output)

    @parameterized.named_parameters(
        ("batch_group", ["batch"], "Usage: git batch"),
        ("batch_prune_group", ["batch", "prune"], "Usage: git batch prune"),
        ("gh_group", ["gh"], "Usage: git gh"),
        ("gk_group", ["gk"], "Usage: git gk"),
    )
    def test_no_args_renders_help_with_usage_and_examples(
        self, args, expected_usage
    ):
        runner = CliRunner()
        result = runner.invoke(
            app,
            args,
            prog_name="git",
            env={"FORCE_COLOR": "1", "TERM": "xterm-256color"},
        )
        output = _strip_ansi(result.output)
        self.assertIn(result.exit_code, (0, 2))
        self.assertIn(expected_usage, output)
        self.assertIn("Examples:", output)


if __name__ == "__main__":
    absltest.main()
