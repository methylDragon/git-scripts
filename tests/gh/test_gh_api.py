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
    gh_stack_checkout,
    gh_stack_link,
    gh_stack_unstack,
    gh_stack_view,
)


@patch("subprocess.run")
def test_check_gh_installed_returns_true_when_gh_version_succeeds(mock_run):
    mock_run.return_value.returncode = 0
    assert check_gh_installed() is True


@patch("subprocess.run")
def test_check_gh_installed_returns_false_when_gh_version_exits_nonzero(
    mock_run,
):
    mock_run.return_value.returncode = 1
    assert check_gh_installed() is False


@patch("subprocess.run")
def test_check_gh_installed_returns_false_when_gh_binary_is_missing(mock_run):
    mock_run.side_effect = FileNotFoundError()
    assert check_gh_installed() is False


@patch("subprocess.run")
def test_get_open_prs_parses_json_list_into_branch_keyed_dict(mock_run):
    mock_run.return_value.stdout = """[
      {
        "headRefName": "feat-a",
        "baseRefName": "main",
        "url": "https://github.com/pr/1", "number": 1
      }
    ]"""
    result = get_open_prs(".")
    assert "feat-a" in result
    assert result["feat-a"].base_ref == "main"
    assert result["feat-a"].url == "https://github.com/pr/1"
    assert result["feat-a"].number == 1


@patch("subprocess.run")
def test_get_open_prs_returns_empty_dict_when_gh_command_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    assert get_open_prs(".") == {}


@patch("subprocess.run")
def test_gh_pr_edit_updates_base_branch_by_pr_number(mock_run):
    gh_pr_edit(".", "feat-a", "main", pr_number="123")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_pr_edit_falls_back_to_branch_name_when_pr_number_is_omitted(
    mock_run,
):
    gh_pr_edit(".", "feat-a", "main")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_pr_edit_raises_gh_execution_error_when_cli_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_pr_edit(".", "feat-a", "main", pr_number="123")


@patch("subprocess.run")
def test_gh_stack_unstack_raises_gh_execution_error_when_cli_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_stack_unstack(".")


@patch("subprocess.run")
def test_gh_stack_link_raises_gh_execution_error_when_cli_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_stack_link(".", ["a", "b"])


@patch("subprocess.run")
def test_gh_stack_view_returns_parsed_json_payload_on_success(mock_run):
    mock_run.return_value.stdout = '{"some": "data"}'
    res = gh_stack_view(".")
    assert res == {"some": "data"}


@patch("subprocess.run")
def test_gh_stack_view_returns_empty_dict_when_cli_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    res = gh_stack_view(".")
    assert res == {}


@patch("subprocess.run")
def test_gh_stack_checkout_invokes_gh_stack_checkout_with_stack_id(mock_run):
    gh_stack_checkout(".", "id")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_stack_checkout_raises_gh_execution_error_when_cli_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_stack_checkout(".", "id")


@patch("subprocess.run")
def test_gh_pr_create_invokes_gh_pr_create_with_title_and_body(mock_run):
    gh_pr_create(".", "feat-a", "main", title="T", body="B")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_pr_create_raises_gh_execution_error_when_cli_fails(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "gh", stderr="Error"
    )
    with pytest.raises(GhExecutionError):
        gh_pr_create(".", "feat-a", "main", title="T", body="B")


@patch("subprocess.run")
def test_check_gh_stack_installed_returns_true_when_extension_is_listed(
    mock_run,
):
    mock_run.return_value.stdout = "gh-stack"
    assert check_gh_stack_installed() is True


@patch("subprocess.run")
def test_check_gh_stack_installed_returns_false_when_extension_check_fails(
    mock_run,
):
    mock_run.side_effect = GhExecutionError("err")
    assert check_gh_stack_installed() is False


@patch("subprocess.run")
def test_gh_stack_link_invokes_gh_stack_link_for_branch_chain(mock_run):
    gh_stack_link(".", ["feat-a", "feat-b"])
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_stack_link_skips_cli_call_when_branch_list_is_empty(mock_run):
    gh_stack_link(".", [])
    mock_run.assert_not_called()


@patch("subprocess.run")
def test_gh_stack_unstack_invokes_default_unstack_when_no_args_given(mock_run):
    gh_stack_unstack(".")
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_gh_stack_unstack_passes_stack_number_and_local_flag_when_specified(
    mock_run,
):
    gh_stack_unstack(".", stack_number="1", local=True)
    mock_run.assert_called_once()
