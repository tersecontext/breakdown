import asyncio
import logging
from dataclasses import dataclass

from claude_agent_sdk import (
    ClaudeAgentOptions,
    CLIConnectionError,
    CLINotFoundError,
    ResultMessage,
    query,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def chat(self, system: str, messages: list[dict]) -> LLMResponse:
        if not messages:
            raise ValueError("messages must not be empty")

        # Format multi-turn history into the prompt; last message is the actual prompt
        prompt_lines = []
        for msg in messages[:-1]:
            role = msg.get("role", "user").capitalize()
            prompt_lines.append(f"{role}: {msg.get('content', '')}")
        last_content = messages[-1].get("content", "")
        prompt = "\n".join(prompt_lines + [last_content]) if prompt_lines else last_content

        delays = [1, 2, 4]
        last_error: Exception | None = None

        for attempt, delay in enumerate([0] + delays):
            if delay:
                await asyncio.sleep(delay)
            try:
                result_content: str | None = None
                async for message in query(
                    prompt=prompt,
                    options=ClaudeAgentOptions(
                        system_prompt=system,
                        model=self.model,
                        allowed_tools=[],
                    ),
                ):
                    if isinstance(message, ResultMessage):
                        result_content = message.result

                if result_content is None:
                    raise RuntimeError("No result received from Claude CLI")

                return LLMResponse(
                    content=result_content,
                    input_tokens=0,
                    output_tokens=0,
                    model=self.model,
                )
            except CLINotFoundError:
                logger.error("Claude Code CLI not found — install with: pip install claude-agent-sdk")
                raise
            except CLIConnectionError as e:
                last_error = e
                if attempt < len(delays):
                    logger.warning("CLI connection error, retrying (attempt %d/3): %s", attempt + 1, e)
                    continue
                logger.error("CLI connection failed after 3 retries")
                raise
            except Exception as e:
                logger.error("Unexpected error calling Claude CLI: %s", e)
                raise

        raise last_error
