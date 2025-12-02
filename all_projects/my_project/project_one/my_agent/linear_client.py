"""Linear API client for CI Boss agent.

This module provides functions to interact with Linear GraphQL API:
- Create Linear issues for test failures
- Update existing issues with new comments
- Link CI runs to Linear issues
"""

import os
import logging
from typing import Optional
import requests
from .graph import CIState

logger = logging.getLogger(__name__)

LINEAR_API_BASE = "https://api.linear.app/graphql"


def get_linear_config() -> tuple[Optional[str], Optional[str], dict[str, Optional[str]]]:
    """Get Linear configuration from environment variables.
    
    Returns:
        Tuple of (api_key, team_id, labels_dict) where labels_dict contains
        optional label IDs for bug, test_failure, and feature.
    """
    api_key = os.getenv("LINEAR_API_KEY")
    team_id = os.getenv("LINEAR_TEAM_ID")
    
    if not api_key:
        logger.warning("LINEAR_API_KEY not set - Linear integration will be skipped")
    if not team_id:
        logger.warning("LINEAR_TEAM_ID not set - Linear integration will be skipped")
    
    labels = {
        "bug": os.getenv("LINEAR_LABEL_ID_BUG"),
        "test_failure": os.getenv("LINEAR_LABEL_ID_TEST_FAILURE"),
        "feature": os.getenv("LINEAR_LABEL_ID_FEATURE"),
    }
    
    return api_key, team_id, labels


def create_linear_issue(
    api_key: str,
    team_id: str,
    title: str,
    description: str,
    label_ids: Optional[list[str]] = None,
) -> Optional[dict]:
    """Create a new Linear issue.
    
    Args:
        api_key: Linear API key
        team_id: Linear team ID
        title: Issue title
        description: Issue description
        label_ids: Optional list of label IDs to attach
    
    Returns:
        Dictionary with issue data including id, url, identifier, or None on failure
    """
    mutation = """
    mutation IssueCreate($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue {
          id
          url
          identifier
        }
      }
    }
    """
    
    variables = {
        "input": {
            "teamId": team_id,
            "title": title,
            "description": description,
        }
    }
    
    if label_ids:
        variables["input"]["labelIds"] = label_ids
    
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    
    payload = {
        "query": mutation,
        "variables": variables,
    }
    
    try:
        response = requests.post(LINEAR_API_BASE, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            logger.error(f"Linear GraphQL errors: {data['errors']}")
            return None
        
        issue_data = data.get("data", {}).get("issueCreate", {})
        if not issue_data.get("success"):
            logger.error("Linear issue creation returned success=false")
            return None
        
        issue = issue_data.get("issue")
        if not issue:
            logger.error("Linear issue creation returned no issue data")
            return None
        
        logger.info(f"Created Linear issue: {issue.get('identifier', issue.get('id'))}")
        return issue
        
    except requests.RequestException as e:
        logger.error(f"Failed to create Linear issue: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                error_data = e.response.json()
                logger.error(f"Response: {error_data}")
            except:
                logger.error(f"Response status: {e.response.status_code}, body: {e.response.text[:500]}")
        return None


def add_linear_comment(
    api_key: str,
    issue_id: str,
    body: str,
) -> bool:
    """Add a comment to an existing Linear issue.
    
    Args:
        api_key: Linear API key
        issue_id: Linear issue ID
        body: Comment body
    
    Returns:
        True if successful, False otherwise
    """
    mutation = """
    mutation CommentCreate($input: CommentCreateInput!) {
      commentCreate(input: $input) {
        success
        comment {
          id
        }
      }
    }
    """
    
    variables = {
        "input": {
            "issueId": issue_id,
            "body": body,
        }
    }
    
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    
    payload = {
        "query": mutation,
        "variables": variables,
    }
    
    try:
        response = requests.post(LINEAR_API_BASE, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "errors" in data:
            logger.error(f"Linear GraphQL errors: {data['errors']}")
            return False
        
        comment_data = data.get("data", {}).get("commentCreate", {})
        if not comment_data.get("success"):
            logger.error("Linear comment creation returned success=false")
            return False
        
        logger.info(f"Added comment to Linear issue {issue_id}")
        return True
        
    except requests.RequestException as e:
        logger.error(f"Failed to add Linear comment: {e}")
        return False


def create_or_update_linear_issue(state: CIState) -> CIState:
    """Create or update a Linear issue for the current CI state.
    
    Behavior:
      - If LINEAR_API_KEY or LINEAR_TEAM_ID are missing, log and return state unchanged.
      - If state["linear_issue_id"] is already set:
          - Append a comment to that issue describing the latest test run.
      - Else:
          - Create a new issue with:
              title: e.g. "[CI] Playwright failure on {repo}@{short_sha}"
              description: includes PR number, commit, changed files, summary, and truncated logs.
              labels: (optional) bug / test-failure label IDs from env.
          - Store issue id + URL / identifier back onto state.
    
    Args:
        state: Current CI state
    
    Returns:
        Updated CI state with linear_issue_id, linear_issue_url, linear_issue_identifier set if created
    """
    api_key, team_id, labels = get_linear_config()
    
    if not api_key or not team_id:
        logger.info("Skipping Linear integration - missing API key or team ID")
        return state
    
    repo = state.get("repo", "unknown/unknown")
    commit_sha = state.get("commit_sha")
    pr_number = state.get("pr_number")
    test_status = state.get("test_status", "pending")
    summary = state.get("summary")
    test_logs = state.get("test_logs")
    changed_files = state.get("changed_files", [])
    
    # Only create/update issues for failures
    if test_status != "failed":
        logger.debug(f"Skipping Linear issue creation - test status is {test_status}")
        return state
    
    short_sha = commit_sha[:7] if commit_sha else "unknown"
    existing_issue_id = state.get("linear_issue_id")
    
    if existing_issue_id:
        # Update existing issue with a comment
        comment_lines = [
            f"## CI Run Update",
            f"**Status**: {test_status.upper()}",
        ]
        
        if commit_sha:
            comment_lines.append(f"**Commit**: `{short_sha}`")
        if pr_number:
            comment_lines.append(f"**PR**: #{pr_number}")
        if summary:
            comment_lines.extend(["", "**Summary**:", summary])
        if test_logs:
            truncated_logs = test_logs[:3000] + "..." if len(test_logs) > 3000 else test_logs
            comment_lines.extend(["", "**Test Logs**:", "```", truncated_logs, "```"])
        
        comment_body = "\n".join(comment_lines)
        success = add_linear_comment(api_key, existing_issue_id, comment_body)
        
        if success:
            logger.info(f"Updated Linear issue {existing_issue_id} with new comment")
        else:
            logger.warning(f"Failed to update Linear issue {existing_issue_id}")
        
        return state
    
    # Create new issue
    title = f"[CI] Playwright failure on {repo}@{short_sha}"
    
    description_lines = [
        f"**Repository**: {repo}",
        f"**Commit**: `{short_sha}`",
    ]
    
    if pr_number:
        description_lines.append(f"**PR**: #{pr_number}")
    
    if changed_files:
        files_list = "\n".join(f"- `{f}`" for f in changed_files[:20])  # Limit to 20 files
        if len(changed_files) > 20:
            files_list += f"\n- ... and {len(changed_files) - 20} more files"
        description_lines.extend(["", "**Changed Files**:", files_list])
    
    if summary:
        description_lines.extend(["", "**Summary**:", summary])
    
    if test_logs:
        truncated_logs = test_logs[:5000] + "\n\n... (truncated)" if len(test_logs) > 5000 else test_logs
        description_lines.extend(["", "**Test Logs**:", "```", truncated_logs, "```"])
    
    description = "\n".join(description_lines)
    
    # Collect label IDs
    label_ids = []
    if labels.get("test_failure"):
        label_ids.append(labels["test_failure"])
    if labels.get("bug"):
        label_ids.append(labels["bug"])
    
    issue = create_linear_issue(
        api_key=api_key,
        team_id=team_id,
        title=title,
        description=description,
        label_ids=label_ids if label_ids else None,
    )
    
    if issue:
        state["linear_issue_id"] = issue.get("id")
        state["linear_issue_url"] = issue.get("url")
        state["linear_issue_identifier"] = issue.get("identifier")
        logger.info(f"Created Linear issue: {issue.get('identifier')}")
    else:
        logger.warning("Failed to create Linear issue")
    
    return state
