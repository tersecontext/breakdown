# Breakdown — Execution plan

## Dependency graph

```
Layer 0:  [0: scaffold]
              |
Layer 1:  [1: database]
           /  |  \
Layer 2:  [2a: TC]  [2b: Anthropic]  [2c: Auth]    ← parallel
           \      |      /
Layer 3:  [3: task engine + research + redis]
              /       \
Layer 4:  [4a: frontend]  [4b: slack bot]            ← parallel
              \       /
Layer 5:  [5: docker compose]
              |
Layer 6:  [6: tests]
```

## Setup

```bash
mkdir breakdown && cd breakdown
git init
git add CLAUDE.md PLAN.md
mkdir -p subtasks/{0-scaffold,1-database,2a-tc-client,2b-anthropic-client,2c-auth,3-task-engine,4a-frontend,4b-slack-bot,5-docker,6-tests}
# Copy each subtask's CLAUDE.md into its directory
git add subtasks/
git commit -m "initial: spec, plan, and subtask definitions"
```

---

## Layer 0 — sequential

### Subtask 0: Scaffold

```bash
git worktree add -b feature/scaffold ../breakdown-scaffold
cp CLAUDE.md ../breakdown-scaffold/
cp subtasks/0-scaffold/CLAUDE.md ../breakdown-scaffold/SUBTASK.md
cd ../breakdown-scaffold
# Run Claude Code: "Build subtask 0 from SUBTASK.md. Reference CLAUDE.md for the full project spec."
```

After verify passes:
```bash
cd ../breakdown
git merge feature/scaffold
git worktree remove ../breakdown-scaffold
```

---

## Layer 1 — sequential

### Subtask 1: Database

```bash
git worktree add -b feature/database ../breakdown-database
cp subtasks/1-database/CLAUDE.md ../breakdown-database/SUBTASK.md
cd ../breakdown-database
# Run Claude Code: "Build subtask 1 from SUBTASK.md. Reference CLAUDE.md for schemas."
```

After verify passes:
```bash
cd ../breakdown
git merge feature/database
git worktree remove ../breakdown-database
```

---

## Layer 2 — parallel (run all three simultaneously)

Open three terminals. All three branch from main after subtask 1 is merged.

### Terminal 1: Subtask 2a — TerseContext client

```bash
git worktree add -b feature/tc-client ../breakdown-tc-client
cp subtasks/2a-tc-client/CLAUDE.md ../breakdown-tc-client/SUBTASK.md
cd ../breakdown-tc-client
# Run Claude Code: "Build subtask 2a from SUBTASK.md."
```

### Terminal 2: Subtask 2b — Anthropic client

```bash
git worktree add -b feature/anthropic-client ../breakdown-anthropic-client
cp subtasks/2b-anthropic-client/CLAUDE.md ../breakdown-anthropic-client/SUBTASK.md
cd ../breakdown-anthropic-client
# Run Claude Code: "Build subtask 2b from SUBTASK.md."
```

### Terminal 3: Subtask 2c — Auth + users

```bash
git worktree add -b feature/auth ../breakdown-auth
cp subtasks/2c-auth/CLAUDE.md ../breakdown-auth/SUBTASK.md
cd ../breakdown-auth
# Run Claude Code: "Build subtask 2c from SUBTASK.md."
```

After all three verify:
```bash
cd ../breakdown
git merge feature/tc-client
git merge feature/anthropic-client
git merge feature/auth
git worktree remove ../breakdown-tc-client
git worktree remove ../breakdown-anthropic-client
git worktree remove ../breakdown-auth
```

If merge conflicts: resolve them (unlikely — each touches different files).

---

## Layer 3 — sequential

### Subtask 3: Task engine + research + Redis

```bash
git worktree add -b feature/task-engine ../breakdown-task-engine
cp subtasks/3-task-engine/CLAUDE.md ../breakdown-task-engine/SUBTASK.md
cd ../breakdown-task-engine
# Run Claude Code: "Build subtask 3 from SUBTASK.md. This is the core — task API, research engine, Redis queue."
```

After verify passes:
```bash
cd ../breakdown
git merge feature/task-engine
git worktree remove ../breakdown-task-engine
```

---

## Layer 4 — parallel (run both simultaneously)

Open two terminals.

### Terminal 1: Subtask 4a — React frontend

```bash
git worktree add -b feature/frontend ../breakdown-frontend
cp subtasks/4a-frontend/CLAUDE.md ../breakdown-frontend/SUBTASK.md
cd ../breakdown-frontend
# Run Claude Code: "Build subtask 4a from SUBTASK.md. Build the full React frontend."
```

### Terminal 2: Subtask 4b — Slack bot

```bash
git worktree add -b feature/slack-bot ../breakdown-slack-bot
cp subtasks/4b-slack-bot/CLAUDE.md ../breakdown-slack-bot/SUBTASK.md
cd ../breakdown-slack-bot
# Run Claude Code: "Build subtask 4b from SUBTASK.md."
```

After both verify:
```bash
cd ../breakdown
git merge feature/frontend
git merge feature/slack-bot
git worktree remove ../breakdown-frontend
git worktree remove ../breakdown-slack-bot
```

---

## Layer 5 — sequential

### Subtask 5: Docker Compose

```bash
git worktree add -b feature/docker ../breakdown-docker
cp subtasks/5-docker/CLAUDE.md ../breakdown-docker/SUBTASK.md
cd ../breakdown-docker
# Run Claude Code: "Build subtask 5 from SUBTASK.md. Containerize everything."
```

After verify passes:
```bash
cd ../breakdown
git merge feature/docker
git worktree remove ../breakdown-docker
```

---

## Layer 6 — sequential

### Subtask 6: Tests

```bash
git worktree add -b feature/tests ../breakdown-tests
cp subtasks/6-tests/CLAUDE.md ../breakdown-tests/SUBTASK.md
cd ../breakdown-tests
# Run Claude Code: "Build subtask 6 from SUBTASK.md. Write tests for all critical paths."
```

After verify passes:
```bash
cd ../breakdown
git merge feature/tests
git worktree remove ../breakdown-tests
```

---

## Summary

| Layer | Subtasks | Parallel? | Depends on |
|-------|----------|-----------|------------|
| 0 | scaffold | no | — |
| 1 | database | no | 0 |
| 2 | TC client, Anthropic client, auth | yes (3 sessions) | 1 |
| 3 | task engine + research + redis | no | 2a, 2b, 2c |
| 4 | frontend, slack bot | yes (2 sessions) | 3 |
| 5 | docker compose | no | 4a, 4b |
| 6 | tests | no | 5 |

Total: 9 subtasks, 6 layers, max 3 parallel sessions at layer 2.
