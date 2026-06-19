from __future__ import annotations

from pathlib import Path

import pytest

from agent_advanced import AdvancedAgent
from agent_baseline import BaselineAgent
from config import LabConfig
from memory_store import UserProfileStore, CompactMemoryManager, estimate_tokens
from model_provider import ProviderConfig


# ===================================================================
# Test config helper
# ===================================================================

def make_config(tmp_path: Path) -> LabConfig:
    """Build an isolated config for tests.

    Points ``state_dir`` into ``tmp_path`` and uses a very low compact
    threshold so compaction triggers quickly in tests.
    """

    return LabConfig(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        compact_threshold_tokens=200,   # low threshold for fast compaction
        compact_keep_messages=2,        # keep only 2 recent messages
        model=ProviderConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            temperature=0.0,
            api_key="test-key",
        ),
        judge_model=ProviderConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            temperature=0.0,
            api_key="test-key",
        ),
    )


# ===================================================================
# Tests
# ===================================================================

def test_user_markdown_read_write_edit(tmp_path: Path) -> None:
    """Verify ``User.md`` can be created, updated, and edited."""

    cfg = make_config(tmp_path)
    store = UserProfileStore(cfg.state_dir / "profiles")

    user_id = "test_user"

    # 1. Read default (file does not exist yet)
    content = store.read_text(user_id)
    assert "# User Profile" in content
    assert "(chưa biết)" in content

    # 2. Write custom content
    new_content = "# User Profile\n\n## Name\nDũngCT\n\n## Location\nHuế\n"
    path = store.write_text(user_id, new_content)
    assert path.exists()
    assert store.read_text(user_id) == new_content

    # 3. Edit (find-and-replace)
    changed = store.edit_text(user_id, "Huế", "Đà Nẵng")
    assert changed is True
    assert "Đà Nẵng" in store.read_text(user_id)
    assert "Huế" not in store.read_text(user_id)

    # 4. Edit with non-existent target returns False
    changed = store.edit_text(user_id, "Không có text này", "xyz")
    assert changed is False

    # 5. File size > 0
    assert store.file_size(user_id) > 0

    # 6. Upsert fact
    store.upsert_fact(user_id, "Name", "DũngCT Updated")
    facts = store.facts(user_id)
    assert facts.get("Name") == "DũngCT Updated"


def test_compact_trigger(tmp_path: Path) -> None:
    """Verify long threads trigger compaction."""

    cfg = make_config(tmp_path)

    cm = CompactMemoryManager(
        threshold_tokens=cfg.compact_threshold_tokens,  # 200
        keep_messages=cfg.compact_keep_messages,          # 2
    )

    thread_id = "test_thread"

    # Send many messages to exceed the threshold
    for i in range(20):
        cm.append(thread_id, "user", f"Message {i}: " + "x" * 100)
        cm.append(thread_id, "assistant", f"Reply {i}: " + "y" * 80)

    # Compaction must have happened
    assert cm.compaction_count(thread_id) > 0

    # Context should have a summary
    ctx = cm.context(thread_id)
    assert ctx["summary"]  # non-empty summary
    assert len(ctx["messages"]) <= 10, (
        f"After compaction, messages should be much fewer than 40 total sent. "
        f"Got {len(ctx['messages'])}."
    )


def test_cross_session_recall(tmp_path: Path) -> None:
    """Verify advanced remembers across sessions and baseline does not."""

    cfg = make_config(tmp_path)

    # ---- Advanced Agent ----
    advanced = AdvancedAgent(config=cfg, force_offline=True)

    # Thread 1: provide facts
    advanced.reply("user1", "thread_1", "Chào bạn, mình tên là DũngCT.")
    advanced.reply("user1", "thread_1", "Mình ở Huế và đang làm MLOps engineer.")
    advanced.reply("user1", "thread_1", "Mình thích cà phê sữa đá.")

    # Thread 2 (new session): ask recall question
    result = advanced.reply("user1", "thread_2", "Mình tên gì và đang ở đâu?")
    answer = result["response"].lower()
    assert "dũngct" in answer, f"Advanced should recall name. Got: {answer}"
    assert "huế" in answer, f"Advanced should recall location. Got: {answer}"

    # ---- Baseline Agent ----
    baseline = BaselineAgent(config=cfg, force_offline=True)

    # Thread 1: provide facts
    baseline.reply("user1", "thread_1", "Chào bạn, mình tên là DũngCT.")
    baseline.reply("user1", "thread_1", "Mình ở Huế và đang làm MLOps engineer.")

    # Thread 2 (new session): ask recall
    result_b = baseline.reply("user1", "thread_2", "Mình tên gì và đang ở đâu?")
    answer_b = result_b["response"].lower()
    # Baseline should NOT know the name in a new thread
    assert "dũngct" not in answer_b, f"Baseline should NOT recall across threads. Got: {answer_b}"


def test_compact_reduces_prompt_load_on_long_thread(tmp_path: Path) -> None:
    """Compare prompt load of baseline vs advanced on a long thread.

    After many messages, the advanced agent's cumulative prompt tokens
    should be lower than the baseline's because compaction reduces
    context size in later turns.
    """

    cfg = make_config(tmp_path)

    baseline = BaselineAgent(config=cfg, force_offline=True)
    advanced = AdvancedAgent(config=cfg, force_offline=True)

    thread_id = "long_thread"
    user_id = "user1"

    # Send many messages
    for i in range(30):
        msg = f"Tin nhắn số {i}: đây là nội dung dài để kiểm tra compact memory " + "x" * 50
        baseline.reply(user_id, thread_id, msg)
        advanced.reply(user_id, thread_id, msg)

    baseline_prompt = baseline.prompt_token_usage(thread_id)
    advanced_prompt = advanced.prompt_token_usage(thread_id)

    # Advanced should use fewer cumulative prompt tokens
    assert advanced_prompt < baseline_prompt, (
        f"Advanced ({advanced_prompt}) should use fewer prompt tokens "
        f"than baseline ({baseline_prompt}) on long threads."
    )

    # Advanced should have compacted at least once
    assert advanced.compaction_count(thread_id) > 0


# ===================================================================
# Run with pytest
# ===================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
