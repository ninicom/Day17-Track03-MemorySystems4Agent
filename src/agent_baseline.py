from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import LabConfig, load_config
from memory_store import estimate_tokens
from model_provider import build_chat_model


@dataclass
class SessionState:
    messages: list[dict[str, str]] = field(default_factory=list)
    token_usage: int = 0
    prompt_tokens_processed: int = 0


class BaselineAgent:
    """Agent A – within-session memory only.

    Requirements:
    - Within-session memory only
    - No persistent ``User.md``
    - Should forget long-term facts across new threads
    """

    def __init__(self, config: LabConfig | None = None, force_offline: bool = False) -> None:
        self.config = config or load_config()
        self.force_offline = force_offline
        self.sessions: dict[str, SessionState] = {}

        # Optionally initialize a real LangChain/LangGraph agent
        self.langchain_agent = None
        if not self.force_offline:
            try:
                self._maybe_build_langchain_agent()
            except Exception:
                pass  # fall back to offline mode

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reply(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Return the agent response and token accounting.

        Routes to the live LangChain path if available, otherwise
        uses the deterministic offline path.
        """

        if self.langchain_agent and not self.force_offline:
            return self._reply_live(user_id, thread_id, message)
        return self._reply_offline(thread_id, message)

    def token_usage(self, thread_id: str) -> int:
        """Cumulative agent token count for one thread."""
        sess = self.sessions.get(thread_id)
        return sess.token_usage if sess else 0

    def prompt_token_usage(self, thread_id: str) -> int:
        """Cumulative prompt context tokens processed across turns.

        For baseline this grows every turn because all messages are
        always carried forward.
        """
        sess = self.sessions.get(thread_id)
        return sess.prompt_tokens_processed if sess else 0

    def compaction_count(self, thread_id: str) -> int:
        """Baseline has no compact memory."""
        return 0

    # ------------------------------------------------------------------
    # Offline (deterministic) path
    # ------------------------------------------------------------------

    def _reply_offline(self, thread_id: str, message: str) -> dict[str, Any]:
        """Deterministic offline behaviour.

        - Stores the user message in session history.
        - Generates a short echo-style reply (no cross-thread memory).
        - Updates token counters.
        """

        sess = self.sessions.setdefault(thread_id, SessionState())

        # Append user message
        sess.messages.append({"role": "user", "content": message})

        # Estimate prompt context = all messages so far
        prompt_ctx = sum(estimate_tokens(m["content"]) for m in sess.messages)
        sess.prompt_tokens_processed += prompt_ctx

        # Generate a simple deterministic response
        response_text = (
            f"[Baseline] Đã nhận tin nhắn của bạn trong thread {thread_id}. "
            f"Tôi chỉ nhớ trong phiên hiện tại ({len(sess.messages)} tin nhắn)."
        )

        # Append assistant reply
        sess.messages.append({"role": "assistant", "content": response_text})
        agent_tokens = estimate_tokens(response_text)
        sess.token_usage += agent_tokens

        return {
            "response": response_text,
            "tokens_used": agent_tokens,
            "prompt_tokens": prompt_ctx,
        }

    # ------------------------------------------------------------------
    # Live LangChain path
    # ------------------------------------------------------------------

    def _reply_live(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Call the live LangChain agent and track tokens."""

        from langchain_core.messages import HumanMessage

        config = {"configurable": {"thread_id": thread_id}}
        result = self.langchain_agent.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=config,
        )

        response_text = result["messages"][-1].content

        # Token accounting
        sess = self.sessions.setdefault(thread_id, SessionState())
        sess.messages.append({"role": "user", "content": message})
        sess.messages.append({"role": "assistant", "content": response_text})

        prompt_ctx = sum(estimate_tokens(m["content"]) for m in sess.messages)
        sess.prompt_tokens_processed += prompt_ctx

        agent_tokens = estimate_tokens(response_text)
        sess.token_usage += agent_tokens

        return {
            "response": response_text,
            "tokens_used": agent_tokens,
            "prompt_tokens": prompt_ctx,
        }

    def _maybe_build_langchain_agent(self):
        """Wire ``create_react_agent`` + ``InMemorySaver`` here.

        Uses ``build_chat_model(self.config.model)`` so the baseline
        can run with any supported provider.
        """

        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.prebuilt import create_react_agent

        llm = build_chat_model(self.config.model)
        memory = MemorySaver()

        self.langchain_agent = create_react_agent(
            model=llm,
            tools=[],
            checkpointer=memory,
        )
