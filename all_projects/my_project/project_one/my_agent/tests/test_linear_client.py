"""Tests for linear_client module."""

import os
import pytest
from unittest.mock import patch, Mock
from my_agent.linear_client import (
    get_linear_config,
    create_linear_issue,
    add_linear_comment,
    create_or_update_linear_issue,
)
from my_agent.graph import CIState


def test_get_linear_config_missing():
    """Test get_linear_config when env vars are missing."""
    with patch.dict(os.environ, {}, clear=True):
        api_key, team_id, labels = get_linear_config()
        assert api_key is None
        assert team_id is None
        assert all(v is None for v in labels.values())


def test_get_linear_config_present():
    """Test get_linear_config when env vars are set."""
    with patch.dict(os.environ, {
        "LINEAR_API_KEY": "test_key",
        "LINEAR_TEAM_ID": "test_team",
        "LINEAR_LABEL_ID_BUG": "bug_label",
    }):
        api_key, team_id, labels = get_linear_config()
        assert api_key == "test_key"
        assert team_id == "test_team"
        assert labels["bug"] == "bug_label"


@patch("my_agent.linear_client.requests.post")
def test_create_linear_issue_success(mock_post):
    """Test create_linear_issue with successful response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "data": {
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "issue_123",
                    "url": "https://linear.app/issue/123",
                    "identifier": "ENG-123",
                }
            }
        }
    }
    mock_response.raise_for_status = Mock()
    mock_post.return_value = mock_response
    
    result = create_linear_issue(
        api_key="test_key",
        team_id="test_team",
        title="Test Issue",
        description="Test description",
    )
    
    assert result is not None
    assert result["id"] == "issue_123"
    assert result["url"] == "https://linear.app/issue/123"
    assert result["identifier"] == "ENG-123"
    mock_post.assert_called_once()


@patch("my_agent.linear_client.requests.post")
def test_create_linear_issue_failure(mock_post):
    """Test create_linear_issue with failed response."""
    mock_post.side_effect = Exception("API error")
    
    result = create_linear_issue(
        api_key="test_key",
        team_id="test_team",
        title="Test Issue",
        description="Test description",
    )
    
    assert result is None


@patch("my_agent.linear_client.requests.post")
def test_add_linear_comment_success(mock_post):
    """Test add_linear_comment with successful response."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "data": {
            "commentCreate": {
                "success": True,
                "comment": {
                    "id": "comment_123",
                }
            }
        }
    }
    mock_response.raise_for_status = Mock()
    mock_post.return_value = mock_response
    
    result = add_linear_comment("test_key", "issue_123", "Test comment")
    
    assert result is True
    mock_post.assert_called_once()


def test_create_or_update_linear_issue_missing_env():
    """Test create_or_update_linear_issue when env vars are missing."""
    with patch.dict(os.environ, {}, clear=True):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "test_status": "failed",
        }
        
        result = create_or_update_linear_issue(state)
        
        # State should be unchanged
        assert result == state
        assert "linear_issue_id" not in result


@patch("my_agent.linear_client.create_linear_issue")
def test_create_or_update_linear_issue_create_new(mock_create):
    """Test create_or_update_linear_issue creating a new issue."""
    mock_create.return_value = {
        "id": "issue_123",
        "url": "https://linear.app/issue/123",
        "identifier": "ENG-123",
    }
    
    with patch.dict(os.environ, {
        "LINEAR_API_KEY": "test_key",
        "LINEAR_TEAM_ID": "test_team",
    }):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "test_status": "failed",
            "summary": "Tests failed",
            "test_logs": "Error details",
        }
        
        result = create_or_update_linear_issue(state)
        
        assert result["linear_issue_id"] == "issue_123"
        assert result["linear_issue_url"] == "https://linear.app/issue/123"
        assert result["linear_issue_identifier"] == "ENG-123"
        mock_create.assert_called_once()


@patch("my_agent.linear_client.add_linear_comment")
def test_create_or_update_linear_issue_update_existing(mock_add_comment):
    """Test create_or_update_linear_issue updating an existing issue."""
    mock_add_comment.return_value = True
    
    with patch.dict(os.environ, {
        "LINEAR_API_KEY": "test_key",
        "LINEAR_TEAM_ID": "test_team",
    }):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "test_status": "failed",
            "linear_issue_id": "existing_issue_123",
            "summary": "Tests failed again",
        }
        
        result = create_or_update_linear_issue(state)
        
        assert result["linear_issue_id"] == "existing_issue_123"
        mock_add_comment.assert_called_once()


def test_create_or_update_linear_issue_skips_non_failures():
    """Test create_or_update_linear_issue skips when test_status != 'failed'."""
    with patch.dict(os.environ, {
        "LINEAR_API_KEY": "test_key",
        "LINEAR_TEAM_ID": "test_team",
    }):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "test_status": "passed",
        }
        
        result = create_or_update_linear_issue(state)
        
        # State should be unchanged (no Linear issue created)
        assert result == state
        assert "linear_issue_id" not in result
