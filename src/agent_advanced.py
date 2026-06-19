from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import LabConfig, load_config
from memory_store import (
    CompactMemoryManager,
    UserProfileStore,
    estimate_tokens,
    extract_profile_updates,
)
from model_provider import build_chat_model


@dataclass
class AgentContext:
    user_id: str
    memory_path: str


class AdvancedAgent:
    """Agent B – Advanced Agent with three memory layers.

    1. within-session memory (compact memory manager)
    2. persistent ``User.md`` (profile store)
    3. compact memory for long threads (summarisation)
    """

    def __init__(self, config: LabConfig | None = None, force_offline: bool = False) -> None:
        self.config = config or load_config()
        self.force_offline = force_offline
        self.profile_store = UserProfileStore(self.config.state_dir / "profiles")
        self.compact_memory = CompactMemoryManager(
            threshold_tokens=self.config.compact_threshold_tokens,
            keep_messages=self.config.compact_keep_messages,
        )
        self.thread_tokens: dict[str, int] = {}
        self.thread_prompt_tokens: dict[str, int] = {}

        # Optionally initialize a real LangChain/LangGraph agent
        self.langchain_agent = None
        if not self.force_offline:
            try:
                self._maybe_build_langchain_agent()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reply(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Route between offline mode and live mode."""

        if self.langchain_agent and not self.force_offline:
            return self._reply_live(user_id, thread_id, message)
        return self._reply_offline(user_id, thread_id, message)

    def token_usage(self, thread_id: str) -> int:
        return self.thread_tokens.get(thread_id, 0)

    def prompt_token_usage(self, thread_id: str) -> int:
        return self.thread_prompt_tokens.get(thread_id, 0)

    def memory_file_size(self, user_id: str) -> int:
        return self.profile_store.file_size(user_id)

    def compaction_count(self, thread_id: str) -> int:
        return self.compact_memory.compaction_count(thread_id)

    # ------------------------------------------------------------------
    # Offline (deterministic) path
    # ------------------------------------------------------------------

    def _reply_offline(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Deterministic advanced path.

        Steps:
        1. Extract stable profile facts from the incoming message.
        2. Persist those facts into ``User.md`` via ``upsert_fact``.
        3. Append the message into compact memory.
        4. Estimate prompt-context load.
        5. Generate a response that can answer long-term recall questions.
        6. Append the assistant reply and update token counters.
        """

        # 1 & 2: Extract and persist profile facts
        facts = extract_profile_updates(message)
        for section, value in facts.items():
            self.profile_store.upsert_fact(user_id, section, value)

        # 3: Append user message into compact memory
        self.compact_memory.append(thread_id, "user", message)

        # 4: Estimate prompt context tokens
        prompt_ctx = self._estimate_prompt_context_tokens(user_id, thread_id)
        self.thread_prompt_tokens[thread_id] = (
            self.thread_prompt_tokens.get(thread_id, 0) + prompt_ctx
        )

        # 5: Generate response
        response_text = self._offline_response(user_id, thread_id, message)

        # 6: Append assistant reply and update token counters
        self.compact_memory.append(thread_id, "assistant", response_text)
        agent_tokens = estimate_tokens(response_text)
        self.thread_tokens[thread_id] = (
            self.thread_tokens.get(thread_id, 0) + agent_tokens
        )

        return {
            "response": response_text,
            "tokens_used": agent_tokens,
            "prompt_tokens": prompt_ctx,
        }

    def _estimate_prompt_context_tokens(self, user_id: str, thread_id: str) -> int:
        """Estimate the context carried into one turn.

        Includes:
        - ``User.md`` content
        - Compact summary text
        - Recent kept messages
        """

        total = 0

        # User.md
        profile_text = self.profile_store.read_text(user_id)
        total += estimate_tokens(profile_text)

        # Compact memory context
        ctx = self.compact_memory.context(thread_id)
        summary = str(ctx.get("summary", ""))
        total += estimate_tokens(summary)

        messages: list[dict[str, str]] = ctx.get("messages", [])  # type: ignore[assignment]
        for m in messages:
            total += estimate_tokens(m.get("content", ""))

        return total

    def _offline_response(self, user_id: str, thread_id: str, message: str) -> str:
        """Return a deterministic answer using persisted memory.

        Handles recall questions by searching ``User.md`` facts.
        For regular messages, acknowledges and confirms stored facts.
        """

        msg_lower = message.lower()
        profile_facts = self.profile_store.facts(user_id)

        # Detect recall / question patterns
        recall_keywords = [
            "tên gì", "tên mình", "nhắc lại", "nhớ lại", "mô tả",
            "tóm tắt", "mình là ai", "nghề gì", "đang ở đâu",
            "style trả lời", "đồ uống", "món ăn", "nuôi con gì",
            "hiện tại mình", "nghề nghiệp", "nơi ở",
        ]
        is_recall_question = any(kw in msg_lower for kw in recall_keywords)

        if is_recall_question and profile_facts:
            # Build a recall response from stored facts
            lines = ["[Advanced] Dựa trên thông tin đã lưu:"]
            for key, val in profile_facts.items():
                lines.append(f"- **{key}**: {val}")
            return "\n".join(lines)

        if profile_facts:
            # Acknowledge and confirm
            fact_summary = ", ".join(
                f"{k}: {v}" for k, v in list(profile_facts.items())[:5]
            )
            return (
                f"[Advanced] Đã nhận và ghi nhớ. "
                f"Thông tin hiện tại: {fact_summary}."
            )

        return (
            "[Advanced] Đã nhận tin nhắn và lưu vào bộ nhớ. "
            "Mình sẽ ghi nhớ các thông tin quan trọng từ cuộc trò chuyện."
        )

    # ------------------------------------------------------------------
    # Live LangChain path
    # ------------------------------------------------------------------

    def _reply_live(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Call the live agent with persistent memory integration."""

        from langchain_core.messages import HumanMessage

        # Extract and persist profile facts
        facts = extract_profile_updates(message)
        for section, value in facts.items():
            self.profile_store.upsert_fact(user_id, section, value)

        # Append to compact memory
        self.compact_memory.append(thread_id, "user", message)

        # Build context-enriched prompt
        profile_text = self.profile_store.read_text(user_id)
        ctx = self.compact_memory.context(thread_id)
        summary = str(ctx.get("summary", ""))

        system_prompt = (
            "Bạn là một trợ lý AI thông minh với bộ nhớ dài hạn.\n\n"
            f"Hồ sơ người dùng:\n{profile_text}\n\n"
        )
        if summary:
            system_prompt += f"Tóm tắt hội thoại cũ:\n{summary}\n\n"

        config = {"configurable": {"thread_id": thread_id}}
        result = self.langchain_agent.invoke(
            {"messages": [
                HumanMessage(content=system_prompt + "\n\nTin nhắn mới: " + message),
            ]},
            config=config,
        )

        response_text = result["messages"][-1].content

        # Append and track
        self.compact_memory.append(thread_id, "assistant", response_text)

        prompt_ctx = self._estimate_prompt_context_tokens(user_id, thread_id)
        self.thread_prompt_tokens[thread_id] = (
            self.thread_prompt_tokens.get(thread_id, 0) + prompt_ctx
        )
        agent_tokens = estimate_tokens(response_text)
        self.thread_tokens[thread_id] = (
            self.thread_tokens.get(thread_id, 0) + agent_tokens
        )

        return {
            "response": response_text,
            "tokens_used": agent_tokens,
            "prompt_tokens": prompt_ctx,
        }

    def _maybe_build_langchain_agent(self):
        """Wire a live agent with tools and compact middleware.

        Uses ``build_chat_model(self.config.model)`` for the selected
        provider, ``InMemorySaver`` for short-term thread state, and
        tools for reading/writing ``User.md``.
        """

        from langchain_core.tools import tool
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.prebuilt import create_react_agent

        store = self.profile_store

        @tool
        def read_user_profile(user_id: str) -> str:
            """Read the User.md profile for a given user."""
            return store.read_text(user_id)

        @tool
        def write_user_profile(user_id: str, section: str, value: str) -> str:
            """Write or update a section in the User.md profile."""
            store.upsert_fact(user_id, section, value)
            return f"Updated {section} = {value}"

        llm = build_chat_model(self.config.model)
        memory = MemorySaver()

        self.langchain_agent = create_react_agent(
            model=llm,
            tools=[read_user_profile, write_user_profile],
            checkpointer=memory,
        )
