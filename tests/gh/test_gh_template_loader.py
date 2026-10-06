"""Unit tests for PR template discovery and commit metadata extraction."""

import os
import tempfile
from unittest.mock import MagicMock

import pygit2
from absl.testing import absltest

from git_scripts.gh.template_loader import (
    compute_pr_metadata,
    get_pr_template,
    humanize_branch_name,
    resolve_repo_workdir,
)


def commit_files_to_ref(
    repo: pygit2.Repository,
    ref_name: str,
    message: str,
    files: dict[str, str],
    parents: list[pygit2.Oid],
) -> pygit2.Oid:
    """Writes nested relative file paths into a commit on ref_name."""
    sig = pygit2.Signature("Test User", "test@example.com")
    root_builder = (
        repo.TreeBuilder(repo[parents[0]].peel(pygit2.Commit).tree)
        if parents
        else repo.TreeBuilder()
    )
    subdirs: dict[str, dict[str, str]] = {}
    for path, content in files.items():
        if "/" in path:
            top, rest = path.split("/", 1)
            subdirs.setdefault(top, {})[rest] = content
        else:
            blob_oid = repo.create_blob(content.encode("utf-8"))
            root_builder.insert(path, blob_oid, pygit2.GIT_FILEMODE_BLOB)

    for top, nested_files in subdirs.items():
        sub_builder = repo.TreeBuilder()
        for sub_path, content in nested_files.items():
            blob_oid = repo.create_blob(content.encode("utf-8"))
            sub_builder.insert(sub_path, blob_oid, pygit2.GIT_FILEMODE_BLOB)
        root_builder.insert(top, sub_builder.write(), pygit2.GIT_FILEMODE_TREE)

    tree_oid = root_builder.write()
    return repo.create_commit(ref_name, sig, sig, message, tree_oid, parents)


class TestGhTemplateLoader(absltest.TestCase):
    """Tests PR template discovery and commit metadata extraction."""

    def test_get_pr_template_matches_case_insensitive_docs_and_subdir_paths(
        self,
    ):
        """Finds PR templates across mixed-case, docs/, and subdir paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gh_dir = os.path.join(tmpdir, ".github")
            os.makedirs(gh_dir)
            mixed_path = os.path.join(gh_dir, "Pull_Request_Template.md")
            with open(mixed_path, "w", encoding="utf-8") as f:
                f.write("## Mixed Case Checklist")
            self.assertEqual(
                get_pr_template(tmpdir), "## Mixed Case Checklist"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = os.path.join(tmpdir, "docs")
            os.makedirs(docs_dir)
            docs_tpl = os.path.join(docs_dir, "pull_request_template.md")
            with open(docs_tpl, "w", encoding="utf-8") as f:
                f.write("## Docs Template")
            self.assertEqual(get_pr_template(tmpdir), "## Docs Template")

        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, ".github", "PULL_REQUEST_TEMPLATE")
            os.makedirs(subdir)
            single_tpl = os.path.join(subdir, "custom.md")
            with open(single_tpl, "w", encoding="utf-8") as f:
                f.write("## Single Subdir Template")
            self.assertEqual(
                get_pr_template(tmpdir), "## Single Subdir Template"
            )

            second_tpl = os.path.join(subdir, "other.md")
            with open(second_tpl, "w", encoding="utf-8") as f:
                f.write("## Second Subdir Template")
            self.assertEqual(get_pr_template(tmpdir), "")

            default_tpl = os.path.join(subdir, "default.md")
            with open(default_tpl, "w", encoding="utf-8") as f:
                f.write("## Subdir Default Template")
            self.assertEqual(
                get_pr_template(tmpdir), "## Subdir Default Template"
            )

    def test_get_pr_template_reads_from_git_commit_tree_when_missing_on_disk(
        self,
    ):
        """Reads the PR template from Git commit trees when absent on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = pygit2.init_repository(tmpdir)
            commit_files_to_ref(
                repo,
                "refs/remotes/origin/main",
                "Initial commit with template",
                {".github/PULL_REQUEST_TEMPLATE.md": "## Committed Template"},
                parents=[],
            )
            commit_files_to_ref(
                repo,
                "refs/remotes/origin/subdir-tpl",
                "Subdir template commit",
                {"PULL_REQUEST_TEMPLATE/custom.md": "## Tree Subdir Template"},
                parents=[],
            )
            self.assertEqual(
                get_pr_template(
                    tmpdir,
                    repo=repo,
                    ref_names=("refs/remotes/origin/main",),
                ),
                "## Committed Template",
            )
            self.assertEqual(
                get_pr_template(
                    tmpdir,
                    repo=repo,
                    ref_names=("refs/remotes/origin/subdir-tpl",),
                ),
                "## Tree Subdir Template",
            )

    def test_compute_pr_metadata_resolves_remote_trunk_without_local_trunk(
        self,
    ):
        """Resolves refs/remotes/<remote>/<base> when local base is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = pygit2.init_repository(tmpdir)
            c1 = commit_files_to_ref(
                repo,
                "refs/remotes/upstream/main",
                "Upstream base",
                {"README.md": "hi"},
                parents=[],
            )
            commit_files_to_ref(
                repo,
                "refs/heads/feat/item",
                "Fix parser\n\nHandles empty tokens.",
                {"parser.py": "pass\n"},
                parents=[c1],
            )

            title, desc = compute_pr_metadata(
                repo,
                "feat/item",
                "main",
                "## Template Footer",
                remote="upstream",
            )
            self.assertEqual(title, "Fix parser")
            self.assertEqual(
                desc, "Handles empty tokens.\n\n## Template Footer"
            )

    def test_resolve_repo_workdir_strips_only_trailing_dot_git_directory(self):
        """Preserves parent directories containing .git in their name."""
        repo = MagicMock(spec=pygit2.Repository)
        repo.workdir = None
        repo.path = "/workspace/my.git/project/.git/"
        self.assertEqual(
            resolve_repo_workdir(repo), "/workspace/my.git/project"
        )
        self.assertEqual(humanize_branch_name("feat/add_login"), "Add login")


if __name__ == "__main__":
    absltest.main()
