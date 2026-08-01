"""Tests for git-align-pr-bases."""

from unittest.mock import MagicMock, patch

import pygit2

from git_scripts.cmd.gh_align_pr_bases_and_sync_stacks import (
    PrCreateAction,
    PrEditAction,
    _execute_creates,
    _execute_edits,
    _get_selected_branches,
    _group_into_stacks,
    _print_branch_summary,
    _print_final_summary,
    _prompt_creates,
    calculate_pr_actions,
    execute_align_pr_bases_and_sync_stacks,
)
from git_scripts.gh.api import GhExecutionError, GitHubPr

# --- FUNCTIONAL CORE TESTS ---


def test_calculate_pr_actions():
    """Test the pure functional core of PR base alignment."""
    # Mock pygit2 repo and branches
    repo = MagicMock(spec=pygit2.Repository)

    # Topology: main -> A -> B -> C -> D
    # PR state: A exists, B missing, C exists, D exists
    # Expected: A -> main, C -> A, D -> C

    branches = {"A", "B", "C", "D"}
    pr_state = {
        "A": GitHubPr(
            headRefName="A",
            baseRefName="main",
            url="http://github.com/A",
            number=1,
        ),
        "C": GitHubPr(
            headRefName="C",
            baseRefName="B",
            url="http://github.com/C",
            number=2,
        ),  # currently points to B
        "D": GitHubPr(
            headRefName="D",
            baseRefName="C",
            url="http://github.com/D",
            number=3,
        ),
    }

    # Mock get_parent_branch logic directly to avoid deep repository stubs.
    def fake_get_parent(r, branch, candidate_branches):
        parents = {
            "A": None,
            "B": "A",
            "C": "B",
            "D": "C",
        }
        return parents.get(branch)

    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
        side_effect=fake_get_parent,
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._compute_pr_metadata",
            return_value=("Title", "Desc"),
        ):
            edits, creates = calculate_pr_actions(
                repo, branches, pr_state, target_trunk="main"
            )

    assert len(edits) == 1
    assert len(creates) == 1

    assert creates[0].branch == "B"

    # C should point to A (since B is missing a PR)
    assert edits[0].branch == "C"
    assert edits[0].old_base == "B"
    assert edits[0].new_base == "A"


def test_calculate_pr_actions_with_tree_topology():
    """Test the PR base alignment with a forking tree topology."""
    repo = MagicMock(spec=pygit2.Repository)

    # Topology:
    # main -> A -> B
    #           -> C -> D
    #           -> E

    branches = {"A", "B", "C", "D", "E"}

    # PR state: A exists, B exists, C missing, D exists, E exists
    pr_state = {
        "A": GitHubPr(
            headRefName="A", baseRefName="main", url="urlA", number=1
        ),
        "B": GitHubPr(
            headRefName="B", baseRefName="main", url="urlB", number=2
        ),  # needs to point to A
        "D": GitHubPr(
            headRefName="D", baseRefName="main", url="urlD", number=3
        ),  # needs to point to A (since C is missing)
        "E": GitHubPr(
            headRefName="E", baseRefName="main", url="urlE", number=4
        ),  # needs to point to A
    }

    def fake_get_parent(r, branch, candidate_branches):
        parents = {
            "A": None,
            "B": "A",
            "C": "A",
            "D": "C",
            "E": "A",
        }
        return parents.get(branch)

    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
        side_effect=fake_get_parent,
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._compute_pr_metadata",
            return_value=("Title", "Desc"),
        ):
            edits, creates = calculate_pr_actions(
                repo, branches, pr_state, target_trunk="main"
            )

    # We expect 3 actions: B->A, D->A, E->A
    assert len(edits) == 3
    assert len(creates) == 1
    assert creates[0].branch == "C"

    actions_dict = {a.branch: a.new_base for a in edits}
    assert actions_dict["B"] == "A"
    assert actions_dict["D"] == "A"  # Skipped C
    assert actions_dict["E"] == "A"


def test_calculate_pr_actions_with_create_missing():
    """Test the PR base alignment with create_missing=True."""
    repo = MagicMock(spec=pygit2.Repository)

    # Topology: main -> A -> B -> C
    # PR state: A exists, C exists
    # If create_missing=True, we should see an edit for C to point to B,
    # and a create for B pointing to A.

    branches = {"A", "B", "C"}

    pr_state = {
        "A": GitHubPr(
            headRefName="A", baseRefName="main", url="urlA", number=1
        ),
        "C": GitHubPr(
            headRefName="C", baseRefName="main", url="urlC", number=2
        ),  # currently points to main, should point to B
    }

    def fake_get_parent(r, branch, candidate_branches):
        parents = {
            "A": None,
            "B": "A",
            "C": "B",
        }
        return parents.get(branch)

    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
        side_effect=fake_get_parent,
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._compute_pr_metadata",
            return_value=("Title", "Desc"),
        ):
            edits, creates = calculate_pr_actions(
                repo,
                branches,
                pr_state,
                target_trunk="main",
                create_missing=True,
            )

    assert len(edits) == 1
    assert len(creates) == 1

    assert edits[0].branch == "C"
    assert edits[0].new_base == "B"

    assert creates[0].branch == "B"
    assert creates[0].base == "A"
    assert creates[0].title == "Title"


# --- CLI INTEGRATION TESTS ---


def test_execute_align_pr_bases_and_sync_stacks_not_installed():
    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_installed",
        return_value=False,
    ):
        assert not execute_align_pr_bases_and_sync_stacks(".", ui=MagicMock())


@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._get_selected_branches"
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_installed",
    return_value=True,
)
def test_execute_align_pr_bases_and_sync_stacks_no_branches(
    mock_installed, mock_get_sel, mock_repo
):
    mock_get_sel.return_value = set()
    assert execute_align_pr_bases_and_sync_stacks(".", ui=MagicMock())


@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._get_selected_branches"
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_installed",
    return_value=True,
)
def test_execute_align_pr_bases_and_sync_stacks_cancel(
    mock_installed, mock_get_sel, mock_repo
):
    mock_get_sel.return_value = None
    assert not execute_align_pr_bases_and_sync_stacks(".", ui=MagicMock())


def test_get_selected_branches():
    repo = MagicMock()
    repo.references = ["refs/heads/prefix-1", "refs/heads/other"]
    repo.head.shorthand = "prefix-1"

    ui = MagicMock()
    ui.auto_yes = True

    res = _get_selected_branches(
        repo,
        "prefix-",
        current_stack_only=True,
        all_matching=False,
        ui=ui,
        target="main",
        interactive=False,
    )
    assert res is not None


@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
def test_execute_align_pr_bases_and_sync_stacks_interactive(
    mock_repo,
):
    ui = MagicMock()
    # Mock ask_checkbox to select a specific tip
    ui.ask_checkbox.return_value = ["b2"]
    ui.auto_yes = False

    repo = MagicMock()
    repo.references = ["refs/heads/b1", "refs/heads/b2", "refs/heads/main"]
    mock_repo.return_value = repo
    repo.head.shorthand = "b2"

    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
        side_effect=lambda r, b, cand: (
            "b1" if b == "b2" else ("main" if b == "b1" else None)
        ),
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._verify_topology",
            return_value=(False, None, None),
        ):
            with patch(
                "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_installed",
                return_value=True,
            ):
                # Run with interactive=True
                execute_align_pr_bases_and_sync_stacks(
                    ".", interactive=True, ui=ui
                )

                # The UI should have been asked for a checkbox
                ui.ask_checkbox.assert_called_once()
                # Ensure the choices were populated correctly
                args, kwargs = ui.ask_checkbox.call_args
                assert "choices" in kwargs


def test_group_into_stacks():
    repo = MagicMock()

    # Mock parent map: b1 -> main, b2 -> b1, c1 -> main
    def fake_get_parent(r, b, pool):
        return {"b1": "main", "b2": "b1", "c1": "main"}.get(b)

    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
        side_effect=fake_get_parent,
    ):
        stacks = _group_into_stacks(repo, {"b1", "b2", "c1"})
        assert "b2" in stacks
        assert "c1" in stacks
        assert "b1" not in stacks
        assert stacks["b2"] == ["b1", "b2"]
        assert stacks["c1"] == ["c1"]


def test_print_branch_summary():
    ui = MagicMock()
    _print_branch_summary(
        {"b1", "b2"},
        {
            "b1": GitHubPr(
                headRefName="b1", baseRefName="main", url="url", number=1
            )
        },
        ui,
    )
    ui.print.assert_called()


def test_prompt_creates():
    ui = MagicMock()
    ui.auto_yes = True
    creates = [PrCreateAction("b1", "main", "T", "D")]
    res = _prompt_creates(creates, True, ui)
    assert len(res) == 1


def test_execute_edits():
    ui = MagicMock()
    edits = [PrEditAction("b1", "old", "new", "reason", "url")]
    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_pr_edit"
    ) as mock_edit:
        assert _execute_edits(edits, ".", ui)
        mock_edit.assert_called_once()

    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_pr_edit",
        side_effect=GhExecutionError("err"),
    ):
        assert not _execute_edits(edits, ".", ui)


def test_execute_creates():
    ui = MagicMock()
    creates = [PrCreateAction("b1", "main", "T", "D")]
    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_pr_create"
    ) as mock_create:
        assert _execute_creates(creates, ".", ui)
        mock_create.assert_called_once()


def test_print_final_summary():
    ui = MagicMock()
    edits = [PrEditAction("b1", "old", "new", "reason", "url")]
    creates = [PrCreateAction("b1", "main", "T", "D")]
    pr_state = {
        "skipped": GitHubPr(
            headRefName="skipped", baseRefName="main", url="url", number=1
        )
    }
    _print_final_summary(
        edits, creates, {"skipped"}, pr_state, ui, stack_branches=["b1"]
    )
    ui.print.assert_called()


@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_stack_installed",
    return_value=True,
)
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_checkout")
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_unstack")
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_link")
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_ancestry",
    return_value=True,
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_continuity",
    return_value=(True, ""),
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_parity",
    return_value=(True, ""),
)
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
def test_execute_align_pr_bases_and_sync_stacks_stack_link_success(
    mock_repo,
    mock_parity,
    mock_cont,
    mock_anc,
    mock_link,
    mock_unstack,
    mock_checkout,
    mock_installed,
):
    ui = MagicMock()
    ui.auto_yes = True
    creates = [
        PrCreateAction("b1", "main", "T", "D"),
        PrCreateAction("b2", "b1", "T", "D"),
    ]
    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._get_selected_branches",
        return_value={"b1", "b2"},
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_open_prs",
            return_value={
                "b1": GitHubPr(
                    headRefName="b1", baseRefName="main", url="url/1", number=1
                )
            },
        ):
            with patch(
                "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.calculate_pr_actions",
                return_value=([], creates),
            ):
                with patch(
                    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._execute_edits",
                    return_value=True,
                ):
                    with patch(
                        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._execute_creates",
                        return_value=True,
                    ):

                        def fake_get_parent(r, branch, candidates):
                            return {"b1": "main", "b2": "b1"}.get(branch)

                        with patch(
                            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
                            side_effect=fake_get_parent,
                        ):
                            execute_align_pr_bases_and_sync_stacks(".", ui=ui)
                            mock_checkout.assert_called_once_with(".", "1")
                            mock_unstack.assert_called_once_with(".")
                            mock_link.assert_called_once_with(
                                ".", ["b1", "b2"]
                            )


@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_stack_installed",
    return_value=True,
)
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_checkout")
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_unstack")
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_link",
    side_effect=GhExecutionError("err"),
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_ancestry",
    return_value=True,
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_continuity",
    return_value=(True, ""),
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_parity",
    return_value=(True, ""),
)
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
def test_execute_align_pr_bases_and_sync_stacks_stack_link_fail(
    mock_repo,
    mock_parity,
    mock_cont,
    mock_anc,
    mock_link,
    mock_unstack,
    mock_checkout,
    mock_installed,
):
    ui = MagicMock()
    ui.auto_yes = True
    creates = [
        PrCreateAction("b1", "main", "T", "D"),
        PrCreateAction("b2", "b1", "T", "D"),
    ]
    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._get_selected_branches",
        return_value={"b1", "b2"},
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_open_prs",
            return_value={
                "b1": GitHubPr(
                    headRefName="b1", baseRefName="main", url="url/1", number=1
                )
            },
        ):
            with patch(
                "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.calculate_pr_actions",
                return_value=([], creates),
            ):
                with patch(
                    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._execute_edits",
                    return_value=True,
                ):
                    with patch(
                        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._execute_creates",
                        return_value=True,
                    ):

                        def fake_get_parent(r, branch, candidates):
                            return {"b1": "main", "b2": "b1"}.get(branch)

                        with patch(
                            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_parent_branch",
                            side_effect=fake_get_parent,
                        ):
                            assert not execute_align_pr_bases_and_sync_stacks(
                                ".", ui=ui
                            )
                            mock_checkout.assert_called_once_with(".", "1")


@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_gh_stack_installed",
    return_value=False,
)
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.gh_stack_link")
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_trunk_ancestry",
    return_value=True,
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_stack_continuity",
    return_value=(True, ""),
)
@patch(
    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.check_remote_push_parity",
    return_value=(True, ""),
)
@patch("git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_repo")
def test_execute_align_pr_bases_and_sync_stacks_stack_link_not_installed(
    mock_repo, mock_parity, mock_cont, mock_anc, mock_link, mock_installed
):
    ui = MagicMock()
    ui.auto_yes = True
    creates = [
        PrCreateAction("b1", "main", "T", "D"),
        PrCreateAction("b2", "b1", "T", "D"),
    ]
    with patch(
        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._get_selected_branches",
        return_value={"b1", "b2"},
    ):
        with patch(
            "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.get_open_prs",
            return_value={},
        ):
            with patch(
                "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks.calculate_pr_actions",
                return_value=([], creates),
            ):
                with patch(
                    "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._execute_edits",
                    return_value=True,
                ):
                    with patch(
                        "git_scripts.cmd.gh_align_pr_bases_and_sync_stacks._execute_creates",
                        return_value=True,
                    ):
                        execute_align_pr_bases_and_sync_stacks(".", ui=ui)
                        mock_link.assert_not_called()
