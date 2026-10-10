"""Unit and integration tests for git-gk-optimize using absltest."""

import json
import os
import shutil
import stat as stat_mod
import struct
import subprocess
import tempfile
from pathlib import Path

from absl.testing import absltest, parameterized

from git_scripts.cmd.gk_optimize import (
    execute_gk_install,
    execute_gk_uninstall,
    execute_gk_verify,
)
from git_scripts.gk.optimize.config_loader import read_config, write_config
from git_scripts.gk.optimize.gitkraken_launcher import write_gitkraken_launcher
from git_scripts.gk.optimize.models import (
    GkExpectMode,
    GkOptimizerConfig,
    GkTagConfig,
)
from git_scripts.gk.optimize.shim_builder import (
    SUPPORTED_GK_VERSIONS,
    build_shim,
    verify_asar_compatibility,
)
from git_scripts.gk.optimize.worktree_watcher import (
    _snapshot_tag_state,
    _snapshot_worktree_heads,
    nudge_worktree_nsfw,
    prune_excess_tags,
    record_prune_marker,
    should_prune_tags,
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
        """Compiles libgk_preload_shim.so once for fast per-test reuse."""
        super().setUpClass()
        cls._shared_shim_dir = tempfile.mkdtemp(prefix="gk_shim_")
        cls._shared_so_path = build_shim(Path(cls._shared_shim_dir))

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

    def test_nsfw_shim_patches_asar_css_and_theme_in_memory_via_read_and_pread(
        self,
    ) -> None:
        """Verifies read/pread on app.asar patch UI CSS and cached refresh."""
        fake_asar = self.tmp_path / "fake_app.asar"
        original_payload = (
            b".right-panel .inner-right-panel{min-height:0;z-index:4;"
            b"display:flex;flex-grow:1;flex-flow:column;"
            b"transition:var(--expand-detail-panel-transition)}\n"
            b'  "expand-detail-panel-transition": '
            b'"flex-grow 250ms ease-in-out",\n'
            b"yield ln.call(Fs.refreshRepo,{activateRefreshSystem:!0,"
            b'blocking:!0,callSource:"RepoSagas.openRepo (usingReduxCache)",'
            b"giveUpOnRefreshThrow:!0})\n"
        )
        fake_asar.write_bytes(original_payload)

        env = dict(os.environ)
        env["LD_PRELOAD"] = str(self._shared_so_path)
        env["GK_ASAR_PATH"] = str(fake_asar)
        probe_code = (
            "import json, os, sys\n"
            "fd = os.open(sys.argv[1], os.O_RDONLY)\n"
            "via_read = os.read(fd, 4096).decode('utf-8')\n"
            "via_pread = os.pread(fd, 4096, 0).decode('utf-8')\n"
            "os.close(fd)\n"
            "print(json.dumps({'read': via_read, 'pread': via_pread}))\n"
        )
        proc = subprocess.run(
            ["python3", "-c", probe_code, str(fake_asar)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout.strip())
        expected_cached = (
            'blocking:!1,callSource:"RepoSagas.openRepo (usingReduxCache)"'
        )
        for key in ("read", "pread"):
            self.assertIn(
                "min-width:0;overflow:hidden;transition:none/***/",
                result[key],
            )
            self.assertIn(
                '"expand-detail-panel-transition": "none"',
                result[key],
            )
            self.assertIn(expected_cached, result[key])
            self.assertEqual(
                len(result[key].encode("utf-8")),
                len(original_payload),
            )
        self.assertEqual(fake_asar.read_bytes(), original_payload)

    def test_nsfw_shim_leaves_non_asar_reads_unmodified(self) -> None:
        """Verifies read/pread on non-ASAR files are not modified."""
        fake_asar = self.tmp_path / "fake_app.asar"
        other_file = self.tmp_path / "other.css"
        payload = (
            b"transition:var(--expand-detail-panel-transition)\n"
            b'"expand-detail-panel-transition": '
            b'"flex-grow 250ms ease-in-out"\n'
        )
        fake_asar.write_bytes(b"empty")
        other_file.write_bytes(payload)

        env = dict(os.environ)
        env["LD_PRELOAD"] = str(self._shared_so_path)
        env["GK_ASAR_PATH"] = str(fake_asar)
        proc = subprocess.run(
            [
                "python3",
                "-c",
                (
                    "import os, sys; fd = os.open(sys.argv[1], os.O_RDONLY);"
                    " sys.stdout.buffer.write(os.pread(fd, 4096, 0));"
                    " os.close(fd)"
                ),
                str(other_file),
            ],
            env=env,
            capture_output=True,
            check=True,
        )
        self.assertEqual(proc.stdout, payload)

    def test_nsfw_shim_strips_ld_preload_in_non_gitkraken_child_processes(
        self,
    ) -> None:
        """Verifies child shells scrub the shim from LD_PRELOAD."""
        env = dict(os.environ)
        env.pop("GK_NSFW_TEST_FORCE", None)
        env.pop("GK_ASAR_PATH", None)
        env["LD_PRELOAD"] = str(self._shared_so_path)
        proc = subprocess.run(
            [
                "python3",
                "-c",
                "import os; print(os.environ.get('LD_PRELOAD', 'UNSET'))",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(proc.stdout.strip(), "UNSET")

    def test_execute_gk_install_prunes_excess_pattern_tags_and_keeps_others(
        self,
    ) -> None:
        """Verifies install trims pattern tags and preserves v* tags."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        custom_yaml = self.tmp_path / "custom.yaml"
        write_config(
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
        write_config(
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
        self.assertNotIn("libgk_preload_shim.so", proc.stdout)
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

    def test_prune_excess_tags_is_noop_when_tags_within_limit(
        self,
    ) -> None:
        """Verifies consecutive tag prune passes do zero writes at limit."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        common_git_dir = main_repo / ".git"
        write_config(
            read_config(keep_recent_override=5),
            common_git_dir / "gk-optimizer" / "config.yaml",
        )

        first_trim = prune_excess_tags(common_git_dir)
        self.assertEqual(first_trim, 17)
        second_trim = prune_excess_tags(common_git_dir)
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
            any("libgk_preload_shim.so" in m for m in res.failures)
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

    def test_read_config_loads_custom_yaml_tag_and_watcher_settings(
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

        parsed = read_config(config_path=custom_yaml)
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

    def test_read_config_overrides_counts_when_keep_recent_set(
        self,
    ) -> None:
        """Verifies default config symlinks and overrides unlink cleanly."""
        default_dest = self.tmp_path / "default_link.yaml"
        write_config(GkOptimizerConfig(), default_dest)
        self.assertTrue(default_dest.is_symlink())

        custom_yaml = self.tmp_path / "custom.yaml"
        write_config(
            GkOptimizerConfig(
                tags=GkTagConfig(
                    keep_recent_by_pattern={"candidate/*": 9, "release/*": 7}
                )
            ),
            custom_yaml,
        )
        self.assertFalse(custom_yaml.is_symlink())

        overridden = read_config(
            config_path=custom_yaml, keep_recent_override=3
        )
        self.assertEqual(
            overridden.tags.keep_recent_by_pattern,
            {"candidate/*": 3, "release/*": 3},
        )

    def test_should_prune_tags_respects_interval_and_flood_tripwire(
        self,
    ) -> None:
        """Verifies 12h cooldown, ISO marker, and packed/loose flood checks."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        common_git_dir = main_repo / ".git"
        prune_excess_tags(common_git_dir)
        marker = record_prune_marker(
            common_git_dir, now_epoch=1000.0, pruned_count=17
        )
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        self.assertIn("T", marker_data["last_prune_iso"])
        self.assertEqual(marker_data["last_pruned_count"], 17)
        self.assertEqual(marker_data["loose_tags_count"], 0)

        self.assertFalse(
            should_prune_tags(common_git_dir, now_epoch=1000.0 + 3600.0)
        )
        self.assertTrue(
            should_prune_tags(common_git_dir, now_epoch=1000.0 + 12.0 * 3600.0)
        )

        # Loose tag flood (> 5 loose tag files) within cooldown triggers prune.
        loose_dir = common_git_dir / "refs" / "tags" / "release" / "assets"
        loose_dir.mkdir(parents=True, exist_ok=True)
        for i in range(6):
            (loose_dir / f"202609{i:02d}.RC00").write_text(
                "0" * 40 + "\n", encoding="utf-8"
            )
        self.assertTrue(
            should_prune_tags(common_git_dir, now_epoch=1000.0 + 10.0)
        )

        # Reset marker and verify >8KB packed-refs flood also triggers prune.
        record_prune_marker(common_git_dir, now_epoch=2000.0)
        (common_git_dir / "packed-refs").write_bytes(b"a" * 40000)
        self.assertTrue(
            should_prune_tags(common_git_dir, now_epoch=2000.0 + 60.0)
        )

    def test_snapshot_tag_state_tracks_nested_tag_subdirectories(self) -> None:
        """Verifies _snapshot_tag_state detects changes in nested tag dirs."""
        main_repo, _ = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        common_git_dir = main_repo / ".git"
        nested_dir = common_git_dir / "refs" / "tags" / "release" / "assets"
        nested_dir.mkdir(parents=True, exist_ok=True)
        before = _snapshot_tag_state(common_git_dir)

        future_mtime = before + 5000.0
        os.utime(nested_dir, (future_mtime, future_mtime))
        after = _snapshot_tag_state(common_git_dir)
        self.assertEqual(after, future_mtime)

    def test_execute_gk_install_replaces_stale_negative_fetch_refspecs(
        self,
    ) -> None:
        """Verifies re-running install prunes obsolete ^refs/tags/* specs."""
        main_repo, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        old_yaml = self.tmp_path / "old.yaml"
        write_config(
            GkOptimizerConfig(
                tags=GkTagConfig(
                    blocked_fetch_patterns=[
                        "candidate/2023*",
                        "release/20*",
                    ]
                )
            ),
            old_yaml,
        )
        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            config_path=old_yaml,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
        )

        new_yaml = self.tmp_path / "new.yaml"
        write_config(
            GkOptimizerConfig(
                tags=GkTagConfig(
                    blocked_fetch_patterns=[
                        "candidate/*",
                        "release/*",
                    ]
                )
            ),
            new_yaml,
        )
        execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            config_path=new_yaml,
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
        self.assertIn("^refs/tags/candidate/*", fetch_specs)
        self.assertIn("^refs/tags/release/*", fetch_specs)
        self.assertNotIn("^refs/tags/candidate/2023*", fetch_specs)
        self.assertNotIn("^refs/tags/release/20*", fetch_specs)

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

        launcher_path, desktop_path = write_gitkraken_launcher(
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

    @staticmethod
    def _write_synthetic_indexed_asar(target_path: Path) -> Path:
        """Writes an indexed Electron ASAR archive with all 3 needles."""
        pkg = b'{"name": "gitkraken", "version": "12.4.0"}'
        css = b"transition:var(--expand-detail-panel-transition)"
        theme = (
            b'"expand-detail-panel-transition": "flex-grow 250ms ease-in-out"'
        )
        render = (
            b'blocking:!0,callSource:"RepoSagas.openRepo (usingReduxCache)"'
        )
        o_css = len(pkg)
        o_theme = o_css + len(css)
        o_render = o_theme + len(theme)
        header_dict = {
            "files": {
                "package.json": {"size": len(pkg), "offset": "0"},
                "src": {
                    "files": {
                        "css": {
                            "files": {
                                "styles.css": {
                                    "size": len(css),
                                    "offset": str(o_css),
                                }
                            }
                        },
                        "main": {
                            "files": {
                                "static": {
                                    "files": {
                                        "themeBases": {
                                            "files": {
                                                "base.jsonc": {
                                                    "size": len(theme),
                                                    "offset": str(o_theme),
                                                }
                                            }
                                        },
                                    }
                                }
                            }
                        },
                        "render": {
                            "files": {
                                "static": {
                                    "files": {
                                        "entryPoints": {
                                            "files": {
                                                "main": {
                                                    "files": {
                                                        "render.bundle.js": {
                                                            "size": len(
                                                                render
                                                            ),
                                                            "offset": str(
                                                                o_render
                                                            ),
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                    }
                                }
                            }
                        },
                    }
                },
            }
        }
        json_bytes = json.dumps(header_dict).encode("utf-8")
        pad_len = (4 - (len(json_bytes) % 4)) % 4
        header_str_sz = len(json_bytes) + 4 + pad_len
        prefix = struct.pack(
            "<IIII", 4, header_str_sz + 4, header_str_sz, len(json_bytes)
        )
        target_path.write_bytes(
            prefix
            + json_bytes
            + (b"\x00" * pad_len)
            + pkg
            + css
            + theme
            + render
        )
        return target_path

    def test_verify_asar_compatibility_reports_matching_and_drifted_patches(
        self,
    ) -> None:
        """Verifies ASAR compatibility detects version and patch drift."""
        compatible_asar = self._write_synthetic_indexed_asar(
            self.tmp_path / "compatible_app.asar"
        )
        missing_res = verify_asar_compatibility(self.tmp_path / "missing.asar")
        self.assertFalse(missing_res.compatible)
        self.assertFalse(missing_res.asar_exists)
        self.assertEqual(len(missing_res.missing_patches), 3)

        ok_res = verify_asar_compatibility(compatible_asar)
        self.assertTrue(ok_res.compatible)
        self.assertEqual(ok_res.detected_version, "12.4.0")
        self.assertEqual(len(ok_res.matched_patches), 3)
        self.assertEqual(ok_res.missing_patches, [])
        self.assertIsNone(ok_res.remediation_hint)

        drifted_asar = self.tmp_path / "drifted_app.asar"
        drifted_asar.write_bytes(
            b'{"name": "gitkraken", "version": "13.0.0"}\n'
            b"transition:var(--expand-detail-panel-transition)\n"
            b'"expand-detail-panel-transition": '
            b'"flex-grow 250ms ease-in-out"\n'
            b'blocking:!0,callSource:"RepoSagas.openRepo (changedInV13)"\n'
        )
        drift_res = verify_asar_compatibility(drifted_asar)
        self.assertFalse(drift_res.compatible)
        self.assertEqual(drift_res.detected_version, "13.0.0")
        self.assertEqual(
            drift_res.missing_patches,
            ["render.bundle.js (cached tab-switch refresh)"],
        )
        self.assertIsNotNone(drift_res.remediation_hint)
        assert drift_res.remediation_hint is not None
        self.assertIn(SUPPORTED_GK_VERSIONS, drift_res.remediation_hint)
        self.assertIn("gk_preload_shim.c", drift_res.remediation_hint)

        _, wt_repo = setup_multi_worktree_gk_repo(
            self.repo_helper, self.tmp_path
        )
        home_dir, _, _ = create_fake_gitkraken_home(self.tmp_path)
        install_ok = execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
            asar_path=compatible_asar,
        )
        self.assertTrue(
            any(
                "3/3 in-memory patches matched" in d
                for d in install_ok.details
            )
        )
        verify_ok = execute_gk_verify(
            repo_path=wt_repo,
            ui=self.ui,
            expect=GkExpectMode.INSTALLED,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
            asar_path=compatible_asar,
        )
        self.assertTrue(verify_ok.passed)
        self.assertTrue(verify_ok.checks["asar_patches_compatible"])

        install_res = execute_gk_install(
            repo_path=wt_repo,
            ui=self.ui,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
            asar_path=drifted_asar,
        )
        self.assertTrue(
            any(
                "WARNING:" in d and "v13.0.0" in d for d in install_res.details
            )
        )

        verify_res = execute_gk_verify(
            repo_path=wt_repo,
            ui=self.ui,
            expect=GkExpectMode.INSTALLED,
            home_dir=home_dir,
            gk_root=home_dir / ".gitkraken",
            asar_path=drifted_asar,
        )
        self.assertFalse(verify_res.passed)
        self.assertIn("asar_patches_compatible", verify_res.failures)


if __name__ == "__main__":
    absltest.main()
