"""GitHub API client for CI Boss agent.

This module provides functions to interact with GitHub REST API:
- Fetch commit and PR metadata
- Get changed files for commits/PRs
- Post PR comments with test results
"""

import os
import logging
from typing import Optional, List, Dict, Any
import requests

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def get_github_token() -> Optional[str]:
    """Get GitHub token from environment variable."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        logger.warning("GITHUB_TOKEN not set - GitHub integration will be skipped")
    return token


def parse_repo(repo: str) -> tuple[str, str]:
    """Parse 'owner/repo' string into (owner, repo) tuple."""
    parts = repo.split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid repo format: {repo}. Expected 'owner/repo'")
    return parts[0], parts[1]


def fetch_pr_head_commit(owner: str, repo: str, pr_number: int, token: str) -> Optional[str]:
    """Fetch the head commit SHA from a PR."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("head", {}).get("sha")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch PR {pr_number}: {e}")
        return None


def fetch_pr_changed_files(owner: str, repo: str, pr_number: int, token: str) -> List[str]:
    """Fetch changed files from a PR."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        files = response.json()
        return [f["filename"] for f in files]
    except requests.RequestException as e:
        logger.error(f"Failed to fetch PR files for PR {pr_number}: {e}")
        return []


def fetch_commit_changed_files(owner: str, repo: str, commit_sha: str, token: str) -> List[str]:
    """Fetch changed files from a commit."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{commit_sha}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        files = data.get("files", [])
        return [f["filename"] for f in files]
    except requests.RequestException as e:
        logger.error(f"Failed to fetch commit files for {commit_sha}: {e}")
        return []


def fetch_commit_message(owner: str, repo: str, commit_sha: str, token: str) -> Optional[str]:
    """Fetch commit message from a commit."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{commit_sha}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("commit", {}).get("message")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch commit message for {commit_sha}: {e}")
        return None


def post_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    comment_body: str,
    token: str,
) -> bool:
    """Post a comment to a PR."""
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    payload = {"body": comment_body}
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Successfully posted comment to PR #{pr_number}")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to post PR comment: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"Response status: {e.response.status_code}, body: {e.response.text[:500]}")
        return False


def format_pr_comment(
    test_status: str,
    summary: Optional[str],
    linear_issue_url: Optional[str],
    test_logs: Optional[str],
    commit_sha: Optional[str] = None,
) -> str:
    """Format a PR comment with test results."""
    status_emoji = "✅" if test_status == "passed" else "❌"
    
    lines = [
        f"## CI Boss Test Results {status_emoji}",
        "",
        f"**Status**: {test_status.upper()}",
    ]
    
    if commit_sha:
        short_sha = commit_sha[:7]
        lines.append(f"**Commit**: `{short_sha}`")
    
    if summary:
        lines.extend(["", "**Summary**:", summary])
    
    if linear_issue_url:
        lines.extend(["", f"**Linked Linear Issue**: {linear_issue_url}"])
    
    if test_logs and test_status == "failed":
        # Truncate logs for readability
        truncated_logs = test_logs[:2000] + "..." if len(test_logs) > 2000 else test_logs
        lines.extend(["", "**Test Logs (truncated)**:", "```", truncated_logs, "```"])
    
    return "\n".join(lines)
