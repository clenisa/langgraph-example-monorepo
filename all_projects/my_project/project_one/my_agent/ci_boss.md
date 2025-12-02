# CI Boss Agent Documentation

The `ci_boss` agent is a CI/CD orchestration agent that integrates with GitHub, Playwright test runner, and Linear issue tracking to automate CI workflows.

## Overview

The CI Boss agent manages the complete CI/CD workflow:
1. **GitHub Integration**: Fetches commit/PR metadata and changed files
2. **Test Execution**: Runs Playwright tests and captures results
3. **Linear Integration**: Creates/updates Linear issues for test failures
4. **PR Comments**: Posts test results as PR comments

## Workflow

The agent follows this graph structure:

```
github → planner → [test_runner | END] → planner → END
```

1. **github node**: Fetches repository information from GitHub API
2. **planner node**: Uses GPT-4o to decide next action:
   - `run_tests`: Execute Playwright tests
   - `analyze_failures`: Analyze failures and create Linear issues
   - `summarize`: Generate final summary and post PR comment
3. **test_runner node**: Executes Playwright tests via subprocess
4. **planner node** (again): Analyzes results and posts PR comments

## Configuration

### Environment Variables

#### Required for GitHub Integration

- `GITHUB_TOKEN`: GitHub Personal Access Token with `repo` scope
  - Used to fetch commit/PR metadata and post PR comments
  - If missing, GitHub integration is skipped (logged warning)

#### Required for Playwright Tests

- `PLAYWRIGHT_COMMAND`: Command to run Playwright tests (optional)
  - Default: `"npx playwright test"`
  - Example: `"npx playwright test --project=chromium"`

- `PLAYWRIGHT_WORKING_DIR`: Working directory for test execution (optional)
  - Default: `/workspace` (repo root)
  - Example: `"/workspace/tests"`

#### Required for Linear Integration

- `LINEAR_API_KEY`: Linear personal API key
  - Get from: Linear → Settings → API → Personal API keys
  - If missing, Linear integration is skipped (logged warning)

- `LINEAR_TEAM_ID`: Linear team ID where issues are created
  - Found in Linear team settings URL: `linear.app/team/{TEAM_ID}/...`
  - If missing, Linear integration is skipped (logged warning)

#### Optional Linear Labels

- `LINEAR_LABEL_ID_BUG`: Label ID for bug issues
- `LINEAR_LABEL_ID_TEST_FAILURE`: Label ID for test failure issues
- `LINEAR_LABEL_ID_FEATURE`: Label ID for feature issues

These are optional - issues will be created without labels if not provided.

## State Schema

The `CIState` TypedDict contains:

```python
class CIState(TypedDict, total=False):
    # Repository information
    repo: str                    # Format: "owner/repo"
    commit_sha: str             # Full commit SHA
    pr_number: Optional[int]    # PR number if applicable
    changed_files: List[str]    # List of changed file paths
    commit_message: Optional[str]  # Commit message
    
    # Test results
    test_status: Literal["pending", "passed", "failed"]
    test_logs: Optional[str]    # Combined stdout/stderr (truncated to 20k chars)
    
    # Planner decisions
    summary: Optional[str]      # Summary from planner
    next_action: Optional[str]   # One of: "run_tests", "analyze_failures", "summarize"
    
    # Linear integration
    linear_issue_id: Optional[str]         # Linear issue UUID
    linear_issue_url: Optional[str]         # Linear issue URL
    linear_issue_identifier: Optional[str]  # Linear issue identifier (e.g., "ENG-123")
```

## Usage

### Starting a CI Run

Invoke the graph with initial state:

```python
from my_agent.graph import graph

initial_state = {
    "repo": "owner/repo",
    "commit_sha": "abc123def456...",
    "pr_number": 42,  # Optional
}

result = graph.invoke(initial_state)
```

### Example State Payload

```json
{
  "repo": "optimaltech/my-repo",
  "commit_sha": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0",
  "pr_number": 123,
  "changed_files": [],
  "test_status": "pending"
}
```

The agent will:
1. Fetch changed files from GitHub (if not provided)
2. Run Playwright tests
3. Create Linear issue if tests fail
4. Post PR comment with results

## Node Details

### github_node

- **Purpose**: Fetch repository metadata from GitHub
- **Inputs**: `repo`, `commit_sha` (optional), `pr_number` (optional)
- **Outputs**: `changed_files`, `commit_message`, `commit_sha` (if derived from PR)
- **Error Handling**: Logs warnings and returns unchanged state if GitHub token is missing or API calls fail

### planner_node

- **Purpose**: Decide next action using GPT-4o
- **Actions**:
  - `run_tests`: Execute tests (routes to test_runner)
  - `analyze_failures`: Analyze failures and create Linear issues (routes to END)
  - `summarize`: Generate summary and post PR comment (routes to END)
- **Side Effects**: 
  - Creates/updates Linear issues when tests fail
  - Posts PR comments when summarizing

### test_runner_node

- **Purpose**: Execute Playwright tests
- **Behavior**: 
  - Skips execution if `next_action != "run_tests"`
  - Runs command from `PLAYWRIGHT_COMMAND` env var
  - Captures stdout/stderr (truncated to 20k chars)
  - Sets `test_status` to "passed" or "failed"
- **Timeout**: 20 minutes (1200 seconds)
- **Error Handling**: Sets `test_status = "failed"` on any error (timeout, command not found, etc.)

## Linear Integration

### Issue Creation

When tests fail and no Linear issue exists:
- Creates a new Linear issue with:
  - Title: `[CI] Playwright failure on {repo}@{short_sha}`
  - Description: Includes repo, commit, PR, changed files, summary, and test logs
  - Labels: Bug and test-failure labels (if configured)
- Stores issue ID, URL, and identifier in state

### Issue Updates

When tests fail and a Linear issue already exists:
- Adds a comment to the existing issue with:
  - Latest test status
  - Commit SHA
  - PR number
  - Summary
  - Test logs

## GitHub PR Comments

When the planner decides to summarize (after tests complete):
- Posts a comment to the PR (if `pr_number` is set) with:
  - Test status (✅ or ❌)
  - Summary
  - Link to Linear issue (if created)
  - Truncated test logs (if failed)

## Error Handling

The agent is designed to be resilient:
- **Missing env vars**: Logs warnings and skips corresponding integrations
- **API failures**: Logs errors but continues graph execution
- **Test execution failures**: Captures error in `test_logs` and sets `test_status = "failed"`
- **Graph never crashes**: All nodes return state even on errors

## Testing

Unit tests are available in `tests/`:
- `test_github_client.py`: Tests for GitHub API functions
- `test_test_runner.py`: Tests for test runner node
- `test_linear_client.py`: Tests for Linear integration

Run tests with:
```bash
pytest all_projects/my_project/project_one/my_agent/tests/
```

## Extending the Agent

### Adding New Integrations

1. Create a new client module (e.g., `slack_client.py`)
2. Add functions that accept `CIState` and return updated state
3. Call from appropriate nodes (e.g., `planner_node` or `test_runner_node`)
4. Use environment variables for configuration
5. Handle missing config gracefully (log and skip)

### Adding New Test Runners

1. Add new node (e.g., `jest_runner_node`)
2. Follow same pattern as `test_runner_node`:
   - Check `next_action`
   - Run command via subprocess
   - Update `test_status` and `test_logs`
3. Add conditional routing in `build_graph()`

### Modifying Planner Behavior

Update the prompt in `planner_node` to change decision logic. The planner should return JSON with `action` and `summary` fields.

## Troubleshooting

### GitHub Integration Not Working

- Check `GITHUB_TOKEN` is set and has `repo` scope
- Verify repo format is `"owner/repo"`
- Check GitHub API rate limits

### Playwright Tests Not Running

- Verify `PLAYWRIGHT_COMMAND` is correct
- Check `PLAYWRIGHT_WORKING_DIR` exists (if set)
- Ensure Playwright is installed in the environment
- Check test logs in `state["test_logs"]`

### Linear Issues Not Created

- Verify `LINEAR_API_KEY` and `LINEAR_TEAM_ID` are set
- Check Linear API key has correct permissions
- Verify team ID is correct
- Check logs for Linear API errors

### PR Comments Not Posted

- Ensure `pr_number` is set in state
- Verify `GITHUB_TOKEN` has `repo` scope
- Check that planner reached "summarize" action
- Review logs for GitHub API errors
