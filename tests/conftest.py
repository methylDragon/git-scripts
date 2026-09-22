"""Shared pytest fixtures for hermetic Git execution in read-only sandboxes."""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _disable_git_gpg_signing() -> None:
    """Disables commit/tag GPG signing so git commit works without ~/.gnupg."""
    os.environ["GIT_CONFIG_COUNT"] = "2"
    os.environ["GIT_CONFIG_KEY_0"] = "commit.gpgsign"
    os.environ["GIT_CONFIG_VALUE_0"] = "false"
    os.environ["GIT_CONFIG_KEY_1"] = "tag.gpgSign"
    os.environ["GIT_CONFIG_VALUE_1"] = "false"
