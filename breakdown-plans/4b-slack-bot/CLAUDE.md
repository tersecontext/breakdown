# Subtask 4b: Slack bot

**Layer:** 4 (parallel — run alongside 4a after subtask 3 merges)
**Branch:** `feature/slack-bot`
**Worktree:** `../breakdown-slack-bot`

## Setup

```bash
cd breakdown
git worktree add -b feature/slack-bot ../breakdown-slack-bot
cp subtasks/4b-slack-bot/CLAUDE.md ../breakdown-slack-bot/SUBTASK.md
cd ../breakdown-slack-bot
```

## What to build

Slack bot for submitting feature requests and reviewing research in threads.

### Slack app setup

- Create `app/clients/slack_bot.py`:
  - Initialize Bolt app with socket mode: `App(token=SLACK_BOT_TOKEN)` + `SocketModeHandler(app, SLACK_APP_TOKEN)`
  - Start as background task in `app/main.py` lifespan

### Message handler

- Listen for messages in the configured SLACK_CHANNEL
- When a user posts a message:
  1. Respond with "Which repo?" + Block Kit button actions (one button per repo from the repos list)
  2. On button click:
     - Look up or auto-create user by Slack username (role='member' if new)
     - Create task via internal store/DB call: feature_name derived from first line of message, description = full message, source_channel='slack', slack_channel_id, slack_thread_ts
     - Post in thread: "Researching..." (the background research task is already kicked off by task creation)

### Research notification

- When a task's research completes (state='researched'), post the research summary in the Slack thread:
  - Summary text
  - Affected files list with change types
  - Complexity: score, label, estimated effort
  - Metrics: files affected, risk areas
  - If the submitter is an admin: include Approve / Reject buttons (Block Kit actions)
  - If the submitter is a member: include "Waiting for admin approval" text

### Approve/Reject buttons

- On Approve click: check if clicking user is admin. If yes, call approve logic, post "Approved by {username}" in thread. If not, respond ephemeral "Only admins can approve."
- On Reject click: same admin check. Post "Rejected by {username}" in thread.

### Error notification

- When research fails (state='failed'): post error message in thread.

### Wire into research engine

- The research engine (from subtask 3) runs as a background task. After it completes, check if source_channel='slack' and post the result to the Slack thread.
- Add a callback mechanism: in `app/engine/researcher.py`, after setting state='researched' or 'failed', call a notification function that checks source_channel and posts to Slack if applicable.

## Verify

```bash
# Configure SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env
uvicorn app.main:app --reload --port 8000

# In #tc-tasks Slack channel:
# Type: "add typescript support to the parser"
# Bot responds with repo buttons
# Click tersecontext
# Bot says "Researching..." in thread
# After 10-15s: research summary appears in thread
# If you're admin: Approve/Reject buttons appear
# Click Approve → "Approved by {username}" posted
# Check Redis: redis-cli XRANGE stream:breakdown-approved - +
```

## Merge

```bash
cd ../breakdown
git merge feature/slack-bot
git worktree remove ../breakdown-slack-bot
```
