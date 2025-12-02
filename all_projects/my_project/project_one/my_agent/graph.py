# my_agent/graph.py
from typing import TypedDict, Literal, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
import json
import re
import logging
import os
import subprocess
from subprocess import TimeoutExpired
from pathlib import Path

from .github_client import (
    get_github_token,
    parse_repo,
    fetch_pr_head_commit,
    fetch_pr_changed_files,
    fetch_commit_changed_files,
    fetch_commit_message,
    post_pr_comment,
    format_pr_comment,
)
from .linear_client import create_or_update_linear_issue

logger = logging.getLogger(__name__)

# 1. Define shared state
class CIState(TypedDict, total=False):
    commit_sha: str
    repo: str
    pr_number: Optional[int]
    changed_files: List[str]
    commit_message: Optional[str]
    test_status: Literal["pending", "passed", "failed"]
    test_logs: Optional[str]
    summary: Optional[str]
    next_action: Optional[str]
    linear_issue_id: Optional[str]
    linear_issue_url: Optional[str]
    linear_issue_identifier: Optional[str]

llm_planner = ChatOpenAI(model="gpt-4o")  # Using gpt-4o as gpt-4.1/o1 may not be available

# 2. Node: planner (master agent)
def planner_node(state: CIState) -> CIState:
    """Decide what to do next based on current state.
    
    Uses GPT-4o to analyze the current CI state and decide on next action:
    - "run_tests": Execute Playwright tests
    - "analyze_failures": Analyze test failures (triggers Linear issue creation)
    - "summarize": Final summary (triggers PR comment posting)
    
    Also handles Linear integration and PR comment posting when appropriate.
    """
    test_status = state.get('test_status', 'pending')
    test_logs_preview = state.get('test_logs', '')[:4000] if state.get('test_logs') else 'N/A'
    next_action = state.get('next_action')
    
    # If tests have failed and we haven't analyzed yet, create/update Linear issue
    if test_status == "failed" and next_action != "analyze_failures":
        state = create_or_update_linear_issue(state)
    
    # Build prompt for planner
    prompt = f"""
You are a CI boss agent orchestrating CI/CD workflows.

IMPORTANT: Always maintain documentation up to date. When you make changes to code, workflows, dependencies, or functionality, you must update the relevant documentation files (README.md, code comments, docstrings) to reflect those changes. Documentation should accurately describe what the code does, what environment variables are needed, and how to use the system.

Current State:
- Repo: {state.get('repo', 'N/A')}
- Commit: {state.get('commit_sha', 'N/A')}
- PR: {state.get('pr_number', 'N/A')}
- Changed files: {state.get('changed_files', [])}
- Test status: {test_status}
- Test logs preview: {test_logs_preview}

Available actions:
1. "run_tests" - Execute Playwright tests (use when test_status is "pending")
2. "analyze_failures" - Analyze test failures and create Linear issues (use when tests failed)
3. "summarize" - Generate final summary and post PR comment (use when tests passed or after analysis)

Decide what to do next based on the current state.
Respond as JSON with exactly this format: {{"action": "run_tests|analyze_failures|summarize", "summary": "brief description of decision"}}
"""
    resp = llm_planner.invoke(prompt)
    
    # Parse response - try to extract JSON from the response
    content = resp.content if hasattr(resp, 'content') else str(resp)
    
    # Try to find JSON in the response (more robust pattern)
    json_match = re.search(r'\{[^{}]*"action"[^{}]*"summary"[^{}]*\}', content, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            action = parsed.get("action", "run_tests")
            summary = parsed.get("summary", "TODO")
        except json.JSONDecodeError:
            action = "run_tests"
            summary = "Failed to parse response"
    else:
        # Fallback parsing
        content_lower = content.lower()
        if "analyze" in content_lower or ("failure" in content_lower and test_status == "failed"):
            action = "analyze_failures"
        elif "summarize" in content_lower or ("success" in content_lower and test_status == "passed"):
            action = "summarize"
        elif test_status == "pending":
            action = "run_tests"
        else:
            action = "summarize"  # Default to summarize if unclear
        summary = content[:200] if len(content) > 200 else content
    
    # Ensure action is one of the valid values
    if action not in ["run_tests", "analyze_failures", "summarize"]:
        logger.warning(f"Invalid action '{action}' from planner, defaulting to 'summarize'")
        action = "summarize"
    
    state["summary"] = summary
    state["next_action"] = action  # type: ignore
    
    # If summarizing and we have PR number, post PR comment
    if action == "summarize":
        pr_number = state.get("pr_number")
        repo = state.get("repo")
        if pr_number and repo:
            token = get_github_token()
            if token:
                try:
                    owner, repo_name = parse_repo(repo)
                    comment_body = format_pr_comment(
                        test_status=test_status,
                        summary=summary,
                        linear_issue_url=state.get("linear_issue_url"),
                        test_logs=state.get("test_logs"),
                        commit_sha=state.get("commit_sha"),
                    )
                    post_pr_comment(owner, repo_name, pr_number, comment_body, token)
                except Exception as e:
                    logger.error(f"Failed to post PR comment: {e}", exc_info=True)
            else:
                logger.debug("Skipping PR comment - GITHUB_TOKEN not set")
    
    return state

# 3. Node: GitHub helper (fetch diff, post comments)
def github_node(state: CIState) -> CIState:
    """
    GitHub helper node - fetch diff, files, post comments.
    
    Fetches commit/PR metadata from GitHub API:
    - If PR number is provided, fetches PR head commit and changed files
    - If only commit SHA is provided, fetches commit changed files
    - Populates changed_files and commit_message in state
    
    Handles missing GITHUB_TOKEN gracefully by logging and returning unchanged state.
    """
    token = get_github_token()
    if not token:
        logger.warning("Skipping GitHub integration - GITHUB_TOKEN not set")
        return state
    
    repo = state.get("repo")
    if not repo:
        logger.warning("No repo specified in state - skipping GitHub fetch")
        return state
    
    try:
        owner, repo_name = parse_repo(repo)
    except ValueError as e:
        logger.error(f"Invalid repo format: {e}")
        return state
    
    commit_sha = state.get("commit_sha")
    pr_number = state.get("pr_number")
    
    # If we have PR number but no commit SHA, fetch PR head commit
    if pr_number and not commit_sha:
        commit_sha = fetch_pr_head_commit(owner, repo_name, pr_number, token)
        if commit_sha:
            state["commit_sha"] = commit_sha
            logger.info(f"Fetched commit SHA {commit_sha[:7]} from PR #{pr_number}")
    
    # Fetch changed files
    if not state.get("changed_files"):
        if pr_number:
            changed_files = fetch_pr_changed_files(owner, repo_name, pr_number, token)
            logger.info(f"Fetched {len(changed_files)} changed files from PR #{pr_number}")
        elif commit_sha:
            changed_files = fetch_commit_changed_files(owner, repo_name, commit_sha, token)
            logger.info(f"Fetched {len(changed_files)} changed files from commit {commit_sha[:7]}")
        else:
            changed_files = []
            logger.warning("No PR number or commit SHA - cannot fetch changed files")
        
        if changed_files:
            state["changed_files"] = changed_files
    
    # Fetch commit message if we have a commit SHA
    if commit_sha and not state.get("commit_message"):
        commit_message = fetch_commit_message(owner, repo_name, commit_sha, token)
        if commit_message:
            state["commit_message"] = commit_message
    
    return state

# 4. Node: test runner – trigger Playwright & capture results
def test_runner_node(state: CIState) -> CIState:
    """
    Test runner node - execute Playwright tests & capture results.
    
    Respects planner decision:
    - If next_action != "run_tests", returns state unchanged
    - Otherwise, runs Playwright tests via subprocess
    
    Configuration:
    - PLAYWRIGHT_COMMAND: Command to run (default: "npx playwright test")
    - PLAYWRIGHT_WORKING_DIR: Working directory for test execution (optional)
    
    Updates state with:
    - test_status: "passed" or "failed"
    - test_logs: Combined stdout/stderr (truncated to 20k chars)
    """
    # Respect planner decision
    next_action = state.get("next_action")
    if next_action != "run_tests":
        logger.debug(f"Skipping test execution - next_action is '{next_action}', not 'run_tests'")
        return state
    
    # Get Playwright command from env or use default
    playwright_cmd = os.getenv("PLAYWRIGHT_COMMAND", "npx playwright test")
    
    # Determine working directory
    working_dir = os.getenv("PLAYWRIGHT_WORKING_DIR")
    if working_dir:
        working_dir = Path(working_dir).resolve()
        if not working_dir.exists():
            logger.error(f"PLAYWRIGHT_WORKING_DIR does not exist: {working_dir}")
            state["test_status"] = "failed"
            state["test_logs"] = f"Error: Working directory does not exist: {working_dir}"
            return state
    else:
        # Default to repo root (workspace root)
        working_dir = Path("/workspace")
    
    logger.info(f"Running Playwright tests: '{playwright_cmd}' in {working_dir}")
    
    try:
        # Split command into list for subprocess (handles shell commands)
        # For simple commands like "npx playwright test", this works
        # For complex shell commands, shell=True might be needed
        cmd_parts = playwright_cmd.split()
        
        # Run with timeout (20 minutes = 1200 seconds)
        result = subprocess.run(
            cmd_parts,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=1200,
        )
        
        # Combine stdout and stderr
        logs = (result.stdout or "") + "\n" + (result.stderr or "")
        
        # Truncate logs to safe length
        max_log_length = 20_000
        if len(logs) > max_log_length:
            logs = logs[:max_log_length] + f"\n... (truncated, total length: {len(logs)})"
        
        state["test_logs"] = logs
        
        if result.returncode == 0:
            state["test_status"] = "passed"
            logger.info("Playwright tests passed")
        else:
            state["test_status"] = "failed"
            logger.warning(f"Playwright tests failed with return code {result.returncode}")
        
    except TimeoutExpired:
        state["test_status"] = "failed"
        state["test_logs"] = "Error: Playwright test execution timed out after 20 minutes"
        logger.error("Playwright test execution timed out")
        
    except FileNotFoundError:
        state["test_status"] = "failed"
        cmd_name = cmd_parts[0] if cmd_parts else playwright_cmd
        state["test_logs"] = f"Error: Command not found: {cmd_name}. Make sure Playwright is installed."
        logger.error(f"Command not found: {cmd_name}")
        
    except Exception as e:
        state["test_status"] = "failed"
        state["test_logs"] = f"Error executing Playwright tests: {str(e)}"
        logger.error(f"Unexpected error running Playwright tests: {e}", exc_info=True)
    
    return state

# 5. Conditional routing function
def route_after_planner(state: CIState) -> str:
    """Route after planner node based on next_action."""
    next_action = state.get("next_action")
    
    if next_action == "run_tests":
        return "test_runner"
    else:
        # analyze_failures or summarize -> end
        return "__end__"


# 6. Wire graph
def build_graph():
    """Build the CI Boss graph with conditional routing."""
    sg = StateGraph(CIState)
    sg.add_node("planner", planner_node)
    sg.add_node("github", github_node)
    sg.add_node("test_runner", test_runner_node)

    # Entry point: github
    sg.set_entry_point("github")
    
    # github -> planner
    sg.add_edge("github", "planner")
    
    # planner -> conditional routing
    sg.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "test_runner": "test_runner",
            "__end__": END,
        },
    )
    
    # test_runner -> planner (loop back for analysis/summary)
    sg.add_edge("test_runner", "planner")

    return sg.compile()

graph = build_graph()
