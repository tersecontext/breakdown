# Subtask 2b: Anthropic client

**Layer:** 2 (parallel — run alongside 2a and 2c after subtask 1 merges)
**Branch:** `feature/anthropic-client`
**Worktree:** `../breakdown-anthropic-client`

## Setup

```bash
cd breakdown
git worktree add -b feature/anthropic-client ../breakdown-anthropic-client
cp subtasks/2b-anthropic-client/CLAUDE.md ../breakdown-anthropic-client/SUBTASK.md
cd ../breakdown-anthropic-client
```

## What to build

Wrap the Anthropic SDK for the research engine.

- Create `app/clients/anthropic.py`:
  - Dataclass `LLMResponse`:
    - `content: str`
    - `input_tokens: int`
    - `output_tokens: int`
    - `model: str`
  - Class `AnthropicClient`:
    - `__init__(self, api_key: str, model: str)`
    - `async def chat(self, system: str, messages: list[dict]) -> LLMResponse`
      - Calls `anthropic.AsyncAnthropic(api_key=...).messages.create()`
      - `model=self.model`, `max_tokens=4096`, `system=system`, `messages=messages`
      - Returns `LLMResponse` with content from `response.content[0].text`, token counts from `response.usage`
    - Error handling:
      - `RateLimitError`: retry 3 times with exponential backoff (1s, 2s, 4s)
      - `AuthenticationError`: log and re-raise immediately
      - Timeout: 30s on the HTTP call
      - All other errors: log and re-raise

## Verify

```bash
python -c "
import asyncio
from app.clients.anthropic import AnthropicClient
from app.config import Settings
async def test():
    s = Settings()
    c = AnthropicClient(s.anthropic_api_key, s.default_model)
    r = await c.chat('You are helpful.', [{'role':'user','content':'Say hello in 5 words'}])
    print(r.content)
    print(f'Tokens: {r.input_tokens}in {r.output_tokens}out, model: {r.model}')
asyncio.run(test())
"
# expect: Claude response + token counts
```

## Merge

```bash
cd ../breakdown
git merge feature/anthropic-client
git worktree remove ../breakdown-anthropic-client
```
