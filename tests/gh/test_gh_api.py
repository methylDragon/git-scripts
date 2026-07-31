import subprocess
from unittest.mock import patch

import pytest

from git_scripts.gh.api import (
    GhExecutionError,
    check_gh_installed,
    check_gh_stack_installed,
    get_open_prs,
    gh_pr_create,
    gh_pr_edit,
    gh_stack_link,
    gh_stack_unstack,
)


@patch("subprocess.run")
def test_check_gh_installed_success(mock_run):
    mock_run.return_value.returncode = 0
    assert check_gh_installed() is True


@patch("subprocess.run")
def test_check_gh_installed_failure(mock_run):
    mock_run.return_value.returncode = 1
    assert check_gh_installed() is False


@patch("subprocess.run")
def test_check_gh_installed_not_found(mock_run):
    mock_run.side_effect = FileNotFoundError()
    assert check_gh_installed() is False


@patch("subprocess.run")
def test_get_open_prs_success(mock_run):
    mock_run.return_value.stdout = """[
      {
        "headRefName": "feat-a",
        "baseRefName": "main",
        "url": "https://github.com/pr/1", "number": 1
      }
    ]"""
    result = get_open_prs(".")
    assert "feat-a" in result
    assert result["feat-a"]["base"] == "main"
    assert result["feat-a"]["url"] == "https://github.com/pr/1"
    assert result["feat-a"]["number"] == "1"


@patch("subprocess.run")
def test_get_open_prs_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    assert get_open_prs(".") == {}


@patch("subprocess.run")
def test_gh_pr_edit_success(mock_run):
    gh_pr_edit(".", "feat-a", "main")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_pr_edit_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_pr_edit(".", "feat-a", "main")


@patch("subprocess.run")
def test_gh_pr_create_success(mock_run):
    gh_pr_create(".", "feat-a", "main", title="T", body="B")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_pr_create_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_pr_create(".", "feat-a", "main", title="T", body="B")


@patch("subprocess.run")
def test_check_gh_stack_installed_success(mock_run):
    mock_run.return_value.stdout = "gh-stack"
    assert check_gh_stack_installed() is True


@patch("subprocess.run")
def test_check_gh_stack_installed_failure(mock_run):
    mock_run.side_effect = GhExecutionError("err")
    assert check_gh_stack_installed() is False


@patch("subprocess.run")
def test_gh_stack_link_success(mock_run):
    gh_stack_link(".", ["feat-a", "feat-b"])
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_stack_link_empty(mock_run):
    gh_stack_link(".", [])
    mock_run.assert_not_called()


@patch("subprocess.run")
def test_gh_stack_unstack_success(mock_run):
    gh_stack_unstack(".")
    mock_run.assert_called_once()
