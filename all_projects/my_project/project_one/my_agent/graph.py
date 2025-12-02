# my_agent/graph.py
from typing import TypedDict, Literal, List, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
import json
import re

# 1. Define shared state
class CIState(TypedDict, total=False):
    commit_sha: str
    repo: str
    pr_number: Optional[int]
    changed_files: List[str]
    test_status: Literal["pending", "passed", "failed"]
    test_logs: Optional[str]
    summary: Optional[str]
    next_action: Optional[str]

llm_planner = ChatOpenAI(model="gpt-4o")  # Using gpt-4o as gpt-4.1/o1 may not be available

# 2. Node: planner (master agent)
def planner_node(state: CIState) -> CIState:
    """Decide what to do next based on current state."""
    # Very rough; in reality you'd craft a better prompt
    test_logs_preview = state.get('test_logs', '')[:4000] if state.get('test_logs') else 'N/A'
    
    prompt = f"""
You are a CI boss agent.

IMPORTANT: Always maintain documentation up to date. When you make changes to code, workflows, dependencies, or functionality, you must update the relevant documentation files (README.md, code comments, docstrings) to reflect those changes. Documentation should accurately describe what the code does, what environment variables are needed, and how to use the system.

Repo: {state.get('repo', 'N/A')}
Commit: {state.get('commit_sha', 'N/A')}
PR: {state.get('pr_number', 'N/A')}
Changed files: {state.get('changed_files', [])}

Test status: {state.get('test_status', 'pending')}
Logs: {test_logs_preview}

Decide: should we (a) run tests, (b) analyze failures, or (c) summarize success?
Respond as JSON: {{"action": "...", "summary": "..." }}
"""
    resp = llm_planner.invoke(prompt)
    
    # Parse response - try to extract JSON from the response
    content = resp.content if hasattr(resp, 'content') else str(resp)
    
    # Try to find JSON in the response
    json_match = re.search(r'\{[^{}]*"action"[^{}]*\}', content)
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
        if "analyze" in content.lower() or "failure" in content.lower():
            action = "analyze_failures"
        elif "summarize" in content.lower() or "success" in content.lower():
            action = "summarize"
        else:
            action = "run_tests"
        summary = content[:200] if len(content) > 200 else content
    
    state["summary"] = summary
    state["next_action"] = action  # type: ignore
    return state

# 3. Node: GitHub helper (fetch diff, post comments) – stubbed
def github_node(state: CIState) -> CIState:
    """
    GitHub helper node - fetch diff, files, post comments.
    In production, implement using PyGithub / direct REST calls.
    """
    # Stub implementation - in production you would:
    # - Use PyGithub or GitHub REST API to fetch changed files
    # - Get diff for the commit/PR
    # - Post review comments if needed
    
    # Example stub: set changed_files if not already set
    if not state.get('changed_files'):
        state['changed_files'] = []  # Would be populated from GitHub API
    
    # Example stub: ensure commit_sha is set
    if not state.get('commit_sha'):
        state['commit_sha'] = 'HEAD'  # Would be from webhook/event
    
    return state

# 4. Node: test runner – trigger Playwright & capture results
def test_runner_node(state: CIState) -> CIState:
    """
    Test runner node - trigger Playwright tests & capture results.
    In production, this would:
    - Call a webhook or GitHub workflow_dispatch
    - Poll for test results
    - Update test_status and test_logs
    """
    # Stub implementation - in production you would:
    # - Trigger test execution (webhook, GitHub Actions workflow_dispatch, etc.)
    # - Poll for completion
    # - Fetch test results and logs
    # - Update state["test_status"] and state["test_logs"]
    
    # Example stub: set test status if not already set
    if not state.get('test_status'):
        state['test_status'] = 'pending'
    
    # In production, after polling:
    # state['test_status'] = 'passed' or 'failed'
    # state['test_logs'] = '... actual test output ...'
    
    return state

# 5. Wire graph
def build_graph():
    sg = StateGraph(CIState)
    sg.add_node("planner", planner_node)
    sg.add_node("github", github_node)
    sg.add_node("test_runner", test_runner_node)

    # One simple flow: github -> planner -> test_runner -> planner -> END
    sg.set_entry_point("github")
    sg.add_edge("github", "planner")
    sg.add_edge("planner", "test_runner")
    sg.add_edge("test_runner", "planner")
    sg.add_edge("planner", END)

    return sg.compile()

graph = build_graph()
