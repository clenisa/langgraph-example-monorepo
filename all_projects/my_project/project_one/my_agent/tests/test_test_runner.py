"""Tests for test_runner_node."""

import os
import pytest
from unittest.mock import patch, Mock
from pathlib import Path
from my_agent.graph import test_runner_node, CIState


def test_test_runner_skips_when_not_run_tests():
    """Test that test_runner_node skips execution when next_action != 'run_tests'."""
    state: CIState = {
        "repo": "owner/repo",
        "commit_sha": "abc123",
        "next_action": "summarize",
        "test_status": "pending",
    }
    
    result = test_runner_node(state)
    
    assert result["test_status"] == "pending"
    assert "test_logs" not in result or result.get("test_logs") is None


@patch("my_agent.graph.subprocess.run")
def test_test_runner_success(mock_run):
    """Test test_runner_node with successful test execution."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Tests passed"
    mock_result.stderr = ""
    mock_run.return_value = mock_result
    
    with patch.dict(os.environ, {"PLAYWRIGHT_COMMAND": "npx playwright test"}):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "next_action": "run_tests",
            "test_status": "pending",
        }
        
        result = test_runner_node(state)
        
        assert result["test_status"] == "passed"
        assert "Tests passed" in result.get("test_logs", "")
        mock_run.assert_called_once()


@patch("my_agent.graph.subprocess.run")
def test_test_runner_failure(mock_run):
    """Test test_runner_node with failed test execution."""
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Tests failed"
    mock_run.return_value = mock_result
    
    with patch.dict(os.environ, {"PLAYWRIGHT_COMMAND": "npx playwright test"}):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "next_action": "run_tests",
            "test_status": "pending",
        }
        
        result = test_runner_node(state)
        
        assert result["test_status"] == "failed"
        assert "Tests failed" in result.get("test_logs", "")
        mock_run.assert_called_once()


@patch("my_agent.graph.subprocess.run")
def test_test_runner_timeout(mock_run):
    """Test test_runner_node with timeout."""
    mock_run.side_effect = TimeoutError("Command timed out")
    
    with patch.dict(os.environ, {"PLAYWRIGHT_COMMAND": "npx playwright test"}):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "next_action": "run_tests",
            "test_status": "pending",
        }
        
        result = test_runner_node(state)
        
        assert result["test_status"] == "failed"
        assert "timeout" in result.get("test_logs", "").lower()


@patch("my_agent.graph.subprocess.run")
def test_test_runner_command_not_found(mock_run):
    """Test test_runner_node when command is not found."""
    mock_run.side_effect = FileNotFoundError("Command not found")
    
    with patch.dict(os.environ, {"PLAYWRIGHT_COMMAND": "nonexistent-command"}):
        state: CIState = {
            "repo": "owner/repo",
            "commit_sha": "abc123",
            "next_action": "run_tests",
            "test_status": "pending",
        }
        
        result = test_runner_node(state)
        
        assert result["test_status"] == "failed"
        assert "not found" in result.get("test_logs", "").lower()
