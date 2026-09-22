"""Unit and integration tests for git-gk-optimize using absltest."""

import json
import os
import shutil
import stat as stat_mod
import subprocess
import tempfile
from pathlib import Path

from absl.testing import absltest, parameterized

from git_scripts.cmd.gk_optimize import (
    execute_gk_install,
    execute_gk_uninstall,
    execute_gk_verify,
)
from git_scripts.gk.optimize.config import (
    read_optimizer_config,
    write_optimizer_config,
)
from git_scripts.gk.optimize.models import (
    GkExpectMode,
    GkOptimizerConfig,
    GkTagConfig,
)
from git_scripts.gk.optimize.shim import (
    build_and_install_shim_so,
    write_gitkraken_launcher_and_desktop,
)
from git_scripts.gk.optimize.watcher import (
    _snapshot_worktree_heads,
    nudge_worktree_nsfw,
    record_tag_prune_marker,
    run_idempotent_tag_trim_pass,
    should_run_tag_trim_pass,
)
from git_scripts.ui import UI
from tests.helpers import (
    GitTestRepo,
    create_fake_gitkraken_home,
    run_git,
    setup_multi_worktree_gk_repo,
)


class TestCmdGkOptimize(parameterized.TestCase):  # pylint: disable=too-many-public-methods
    """Behavioral and boundary tests for git-gk-optimize."""

    _shared_shim_dir: str
    _shared_so_path: Path

    @classmethod
    def setUpClass(cls) -> None:  # pylint: disable=invalid-name
        """Compiles libgk_nsfw_nofollow.so once for fast per-test reuse."""
        super().setUpClass()
        cls._shared_shim_dir = tempfile.mkdtemp(prefix="gk_shim_")
        cls._shared_so_path = build_and_install_shim_so(
            Path(cls._shared_shim_dir)
        )

    @classmethod
    def tearDownClass(cls) -> None:  # pylint: disable=invalid-name
        """Cleans up the shared compiled shim directory."""
        shutil.rmtree(cls._shared_shim_dir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self) -> None:  # pylint: disable=invalid-name
        """Initializes an isolated GitTestRepo and aux directory per test."""
        super().setUp()
        self.repo_helper = GitTestRepo(use_template=False)
        self.tmp_path = Path(self.repo_helper.temp_dir.name).parent / (
            Path(self.repo_helper.temp_dir.name).name + "_aux"
        )
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.ui = UI(plain=True, auto_yes=True)

    def tearDown(self) -> None:  # pylint: disable=invalid-name
        """Cleans up the isolated GitTestRepo and aux directory."""
        shutil.rmtree(self.tmp_path, ignore_errors=True)
        self.repo_helper.cleanup()
        super().tearDown()

    def _probe_shim_stat_mode(self, target_path: Path) -> int:
        """Returns os.stat(target_path).st_mode under LD_PRELOAD of shim."""
        env = dict(os.environ)
        env["LD_PRELOAD"] = str(self._shared_so_path)
        env["GK_NSFW_TEST_FORCE"] = "1"
        env["GK_IGNORED_DIRS"] = "node_modules:.venv:.pixi:target"
        proc = subprocess.run(
            [
                "python3",
                "-c",
                "import os, sys; print(os.stat(sys.argv[1]).st_mode)",
                str(target_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return int(proc.stdout.strip())

    def test_nsfw_shim_resolves_symlinked_repo_root_as_directory(self) -> None:
        """Verifies a symlinked repo root with .git resolves as S_ISDIR."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        symlinked_repo_root = self.tmp_path / "symlink-to-repo"
        symlinked_repo_root.symlink_to(main_repo)

        mode = self._probe_shim_stat_mode(symlinked_repo_root)
        self.assertTrue(stat_mod.S_ISDIR(mode))

    def test_nsfw_shim_reports_child_worktree_symlinks_as_symlinks(
        self,
    ) -> None:
        """Verifies child symlinks (bazel-out) report S_ISLNK not S_ISDIR."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        mode = self._probe_shim_stat_mode(main_repo / "bazel-out")
        self.assertTrue(stat_mod.S_ISLNK(mode))
        self.assertFalse(stat_mod.S_ISDIR(mode))

    def test_nsfw_shim_hides_ignored_build_directories_from_directory_walk(
        self,
    ) -> None:
        """Verifies GK_IGNORED_DIRS entries do not report S_ISDIR."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        node_modules_dir = main_repo / "node_modules"
        node_modules_dir.mkdir()

        mode = self._probe_shim_stat_mode(node_modules_dir)
        self.assertFalse(stat_mod.S_ISDIR(mode))

    def test_execute_gk_install_prunes_excess_pattern_tags_and_keeps_others(
        self,
    ) -> None:
        """Verifies install trims pattern tags and preserves v* tags."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        custom_yaml = self.tmp_path / "custom.yaml"
        write_optimizer_config(
            GkOptimizerConfig(
                tags=GkTagConfig(
                    keep_other_tags=True,
                    keep_recent_by_pattern={
                        "candidate/*": 5,
                        "release/*": 4,
                        "platform/*": 5,
                    },
                )
            ),
            custom_yaml,
        )

        res = execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            config_path=custom_yaml,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )
        self.assertTrue(res.success)
        self.assertEqual(res.pruned_tags_count, 18)
        self.assertEqual(res.kept_tags_count, 12)
        self.assertTrue(
            (main_repo / ".git" / "gk-optimizer" / "state.yaml").is_file()
        )

    def test_execute_gk_install_normalizes_blocked_fetch_patterns(
        self,
    ) -> None:
        """Verifies short tag patterns normalize to ^refs/tags/... specs."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        custom_yaml = self.tmp_path / "custom.yaml"
        write_optimizer_config(
            GkOptimizerConfig(
                tags=GkTagConfig(
                    blocked_fetch_patterns=[
                        "candidate/2023*",
                        "refs/tags/candidate/2024*",
                        "^refs/tags/candidate/2025*",
                    ]
                )
            ),
            custom_yaml,
        )

        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            config_path=custom_yaml,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )
        fetch_specs = (
            run_git(
                ["config", "--get-all", "remote.origin.fetch"],
                cwd=str(main_repo),
            )
            .stdout.strip()
            .splitlines()
        )
        self.assertIn("^refs/tags/candidate/2023*", fetch_specs)
        self.assertIn("^refs/tags/candidate/2024*", fetch_specs)
        self.assertIn("^refs/tags/candidate/2025*", fetch_specs)

    def test_execute_gk_install_preserves_worktree_symlinks_and_open_tabs(
        self,
    ) -> None:
        """Verifies install keeps bazel-* symlinks and repoInitDetails."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, profile_file, _ = create_fake_gitkraken_home(self.tmp_path)

        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )
        self.assertTrue((main_repo / "bazel-out").is_symlink())
        self.assertTrue((wt_repo / "bazel-out").is_symlink())
        self.assertEqual(
            run_git(
                ["status", "--porcelain"], cwd=str(wt_repo)
            ).stdout.strip(),
            "",
        )

        prof_after = json.loads(profile_file.read_text(encoding="utf-8"))
        self.assertIn("openTab1", prof_after["repoInitDetails"])
        self.assertIn("openTab2", prof_after["repoInitDetails"])

    def test_execute_gk_uninstall_restores_tags_without_overwriting_retags(
        self,
    ) -> None:
        """Verifies CAS uninstall restores tags and keeps post-install tags."""
        _, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        gk_root = home_dir / ".gitkraken"

        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            keep_recent_override=5,
            home_dir=home_dir,
            gk_root=gk_root,
        )

        (wt_repo / "new_feature.txt").write_text("hello\n", encoding="utf-8")
        run_git(["add", "new_feature.txt"], cwd=str(wt_repo))
        run_git(["commit", "-m", "post-install commit"], cwd=str(wt_repo))
        post_install_head = run_git(
            ["rev-parse", "HEAD"], cwd=str(wt_repo)
        ).stdout.strip()
        self.repo_helper.tag(
            "candidate/2026-01-01", ref=post_install_head, force=True
        )

        res_uninstall = execute_gk_uninstall(
            repo_path=wt_repo,
            ui=self.ui,
            home_dir=home_dir,
        )
        self.assertTrue(res_uninstall.success)

        verify_uninst = execute_gk_verify(
            repo_path=wt_repo,
            ui=self.ui,
            expect=GkExpectMode.UNINSTALLED,
            home_dir=home_dir,
            gk_root=gk_root,
        )
        self.assertTrue(verify_uninst.passed)
        self.assertEqual(
            self.repo_helper.rev_parse("refs/tags/candidate/2026-01-01"),
            post_install_head,
        )
        self.assertEqual(
            len(self.repo_helper.rev_parse("refs/tags/candidate/2026-01-02")),
            40,
        )

    def test_gitkraken_git_wrapper_scrubs_ld_preload_from_child_env(
        self,
    ) -> None:
        """Verifies gitkraken-git unsets LD_PRELOAD before /usr/bin/git."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )

        gk_git = home_dir / ".config" / "gitkraken-optimizer" / "gitkraken-git"
        env = dict(os.environ)
        env["HOME"] = str(home_dir)
        env["LD_PRELOAD"] = str(self._shared_so_path)
        proc = subprocess.run(
            [str(gk_git), "-c", "alias.printenv=!env", "printenv"],
            cwd=str(main_repo),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertNotIn("libgk_nsfw_nofollow.so", proc.stdout)
        self.assertEqual(proc.stderr, "")

    def test_gitkraken_git_wrapper_filters_ls_remote_tags_to_retention(
        self,
    ) -> None:
        """Verifies gitkraken-git filters ls-remote --tags to top N tags."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            keep_recent_override=5,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )

        gk_git = home_dir / ".config" / "gitkraken-optimizer" / "gitkraken-git"
        env = dict(os.environ)
        env["HOME"] = str(home_dir)
        ls_proc = subprocess.run(
            [str(gk_git), "ls-remote", "--tags", str(main_repo)],
            cwd=str(wt_repo),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("refs/tags/v1.0.0", ls_proc.stdout)
        self.assertIn("refs/tags/candidate/2026-01-15", ls_proc.stdout)
        self.assertNotIn("refs/tags/candidate/2026-01-01", ls_proc.stdout)

    def test_nudge_worktree_nsfw_triggers_move_without_leaving_temp_files(
        self,
    ) -> None:
        """Verifies nudge_worktree_nsfw leaves no temporary .gk-refresh."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        wt_gitdir = next((main_repo / ".git" / "worktrees").iterdir())

        self.assertTrue(nudge_worktree_nsfw(wt_gitdir))
        self.assertFalse((wt_gitdir / ".gk-refresh").exists())

    def test_run_idempotent_tag_trim_pass_is_noop_when_tags_within_limit(
        self,
    ) -> None:
        """Verifies consecutive tag trim passes do zero writes at limit."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        common_git_dir = main_repo / ".git"
        write_optimizer_config(
            read_optimizer_config(keep_recent_override=5),
            common_git_dir / "gk-optimizer" / "config.yaml",
        )

        first_trim = run_idempotent_tag_trim_pass(common_git_dir)
        self.assertEqual(first_trim, 17)
        second_trim = run_idempotent_tag_trim_pass(common_git_dir)
        self.assertEqual(second_trim, 0)

    def test_execute_gk_verify_fails_when_optimizations_are_not_installed(
        self,
    ) -> None:
        """Verifies verify --expect installed fails on unoptimized repo."""
        _, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)

        res = execute_gk_verify(
            repo_path=wt_repo,
            ui=self.ui,
            expect=GkExpectMode.INSTALLED,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )
        self.assertFalse(res.passed)
        self.assertTrue(
            any("libgk_nsfw_nofollow.so" in m for m in res.failures)
        )

    def test_execute_gk_uninstall_returns_false_when_no_saved_state_exists(
        self,
    ) -> None:
        """Verifies uninstall returns success=False without state.yaml."""
        _, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)

        res = execute_gk_uninstall(
            repo_path=wt_repo,
            ui=self.ui,
            home_dir=home_dir,
        )
        self.assertFalse(res.success)

    def test_read_optimizer_config_loads_custom_yaml_tag_and_watcher_settings(
        self,
    ) -> None:
        """Verifies custom YAML tag and watcher settings load into model."""
        custom_yaml = self.tmp_path / "config.yaml"
        custom_yaml.write_text(
            "tags:\n"
            "  keep_other_tags: false\n"
            "  keep_recent_by_pattern:\n"
            '    "candidate/*": 9\n'
            '    "release/*": 7\n'
            "  blocked_fetch_patterns:\n"
            '    - "candidate/2023*"\n'
            "watcher:\n"
            "  ignored_dirs:\n"
            '    - "custom_build_dir"\n',
            encoding="utf-8",
        )

        parsed = read_optimizer_config(config_path=custom_yaml)
        self.assertFalse(parsed.tags.keep_other_tags)
        self.assertEqual(
            parsed.tags.keep_recent_by_pattern,
            {"candidate/*": 9, "release/*": 7},
        )
        self.assertEqual(
            parsed.tags.blocked_fetch_patterns,
            ["candidate/2023*"],
        )
        self.assertEqual(parsed.watcher.ignored_dirs, ["custom_build_dir"])

    def test_read_optimizer_config_overrides_counts_when_keep_recent_set(
        self,
    ) -> None:
        """Verifies keep_recent_override replaces per-pattern tag counts."""
        custom_yaml = self.tmp_path / "custom.yaml"
        write_optimizer_config(
            GkOptimizerConfig(
                tags=GkTagConfig(
                    keep_recent_by_pattern={"candidate/*": 9, "release/*": 7}
                )
            ),
            custom_yaml,
        )

        overridden = read_optimizer_config(
            config_path=custom_yaml, keep_recent_override=3
        )
        self.assertEqual(
            overridden.tags.keep_recent_by_pattern,
            {"candidate/*": 3, "release/*": 3},
        )

    def test_should_run_tag_trim_pass_respects_interval_and_flood_tripwire(
        self,
    ) -> None:
        """Verifies lazy 12h cooldown and >32KB packed-refs flood tripwire."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        common_git_dir = main_repo / ".git"
        record_tag_prune_marker(common_git_dir, now_epoch=1000.0)

        self.assertFalse(
            should_run_tag_trim_pass(common_git_dir, now_epoch=1000.0 + 3600.0)
        )
        self.assertTrue(
            should_run_tag_trim_pass(
                common_git_dir, now_epoch=1000.0 + 12.0 * 3600.0
            )
        )

        (common_git_dir / "packed-refs").write_bytes(b"a" * 40000)
        self.assertTrue(
            should_run_tag_trim_pass(common_git_dir, now_epoch=1000.0 + 60.0)
        )

    def test_snapshot_worktree_heads_ignores_index_mtime_changes(
        self,
    ) -> None:
        """Verifies index stat-cache updates do not alter HEAD signatures."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        common_git_dir = main_repo / ".git"
        wt_gitdir = next((common_git_dir / "worktrees").iterdir())
        before = _snapshot_worktree_heads(common_git_dir)

        idx_file = wt_gitdir / "index"
        idx_file.write_bytes(idx_file.read_bytes())
        os.utime(idx_file, (1999999999, 1999999999))
        after_index_touch = _snapshot_worktree_heads(common_git_dir)
        self.assertEqual(before, after_index_touch)

        run_git(["commit", "--allow-empty", "-m", "new"], cwd=str(wt_repo))
        after_commit = _snapshot_worktree_heads(common_git_dir)
        self.assertNotEqual(before, after_commit)

    def test_desktop_entry_and_launcher_preserve_wm_class_and_exec_pid(
        self,
    ) -> None:
        """Verifies gitkraken.desktop uses StartupWMClass=gitkraken & exec."""
        dest_dir = self.tmp_path / "opt"
        apps_dir = self.tmp_path / "apps"
        common_git_dir = self.tmp_path / "repo" / ".git"
        common_git_dir.mkdir(parents=True)

        launcher_path, desktop_path = write_gitkraken_launcher_and_desktop(
            dest_dir=dest_dir,
            common_git_dir=common_git_dir,
            ignored_dirs=["node_modules", ".venv"],
            applications_dir=apps_dir,
        )
        desktop_text = desktop_path.read_text(encoding="utf-8")
        launcher_text = launcher_path.read_text(encoding="utf-8")

        self.assertIn("StartupWMClass=gitkraken\n", desktop_text)
        self.assertIn("Icon=/usr/share/pixmaps/gitkraken.png\n", desktop_text)
        self.assertIn('--gk-pid "$$"', launcher_text)
        self.assertIn(
            'exec /usr/share/gitkraken/gitkraken "$@"', launcher_text
        )


if __name__ == "__main__":
    absltest.main()
