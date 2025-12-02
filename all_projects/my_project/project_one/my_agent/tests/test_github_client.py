"""Tests for github_client module."""

import os
import pytest
from unittest.mock import patch, Mock
from my_agent.github_client import (
    get_github_token,
    parse_repo,
    fetch_pr_head_commit,
    fetch_pr_changed_files,
    fetch_commit_changed_files,
    fetch_commit_message,
    post_pr_comment,
    format_pr_comment,
)


def test_get_github_token_missing():
    """Test get_github_token when token is not set."""
    with patch.dict(os.environ, {}, clear=True):
        token = get_github_token()
        assert token is None


def test_get_github_token_present():
    """Test get_github_token when token is set."""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"}):
        token = get_github_token()
        assert token == "test_token"


def test_parse_repo_valid():
    """Test parse_repo with valid format."""
    owner, repo = parse_repo("owner/repo")
    assert owner == "owner"
    assert repo == "repo"


def test_parse_repo_invalid():
    """Test parse_repo with invalid format."""
    with pytest.raises(ValueError):
        parse_repo("invalid")


@patch("my_agent.github_client.requests.get")
def test_fetch_pr_head_commit_success(mock_get):
    """Test fetch_pr_head_commit with successful response."""
    mock_response = Mock()
    mock_response.json.return_value = {"head": {"sha": "abc123"}}
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    result = fetch_pr_head_commit("owner", "repo", 1, "token")
    assert result == "abc123"


@patch("my_agent.github_client.requests.get")
def test_fetch_pr_head_commit_failure(mock_get):
    """Test fetch_pr_head_commit with failed response."""
    mock_get.side_effect = Exception("API error")
    
    result = fetch_pr_head_commit("owner", "repo", 1, "token")
    assert result is None


@patch("my_agent.github_client.requests.get")
def test_fetch_pr_changed_files_success(mock_get):
    """Test fetch_pr_changed_files with successful response."""
    mock_response = Mock()
    mock_response.json.return_value = [
        {"filename": "file1.py"},
        {"filename": "file2.py"},
    ]
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    result = fetch_pr_changed_files("owner", "repo", 1, "token")
    assert result == ["file1.py", "file2.py"]


@patch("my_agent.github_client.requests.get")
def test_fetch_commit_changed_files_success(mock_get):
    """Test fetch_commit_changed_files with successful response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "files": [
            {"filename": "file1.py"},
            {"filename": "file2.py"},
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response
    
    result = fetch_commit_changed_files("owner", "repo", "abc123", "token")
    assert result == ["file1.py", "file2.py"]


@patch("my_agent.github_client.requests.post")
def test_post_pr_comment_success(mock_post):
    """Test post_pr_comment with successful response."""
    mock_response = Mock()
    mock_response.raise_for_status = Mock()
    mock_post.return_value = mock_response
    
    result = post_pr_comment("owner", "repo", 1, "Test comment", "token")
    assert result is True
    mock_post.assert_called_once()


def test_format_pr_comment():
    """Test format_pr_comment formatting."""
    comment = format_pr_comment(
        test_status="passed",
        summary="All tests passed",
        linear_issue_url=None,
        test_logs=None,
        commit_sha="abc123",
    )
    
    assert "✅" in comment
    assert "PASSED" in comment
    assert "abc123" in comment
    assert "All tests passed" in comment


def test_format_pr_comment_with_linear():
    """Test format_pr_comment with Linear issue URL."""
    comment = format_pr_comment(
        test_status="failed",
        summary="Tests failed",
        linear_issue_url="https://linear.app/issue/123",
        test_logs="Error: test failed",
        commit_sha="abc123",
    )
    
    assert "❌" in comment
    assert "FAILED" in comment
    assert "linear.app" in comment
    assert "test failed" in comment
