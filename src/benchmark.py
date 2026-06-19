from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from tabulate import tabulate

from agent_advanced import AdvancedAgent
from agent_baseline import BaselineAgent
from config import load_config


@dataclass
class BenchmarkRow:
    agent_name: str
    agent_tokens_only: int
    prompt_tokens_processed: int
    recall_score: float
    response_quality: float
    memory_growth_bytes: int
    compactions: int


# ===================================================================
# Chat Logger
# ===================================================================

class ChatLogger:
    """Ghi lại toàn bộ đoạn chat giữa user và agent vào folder log.

    Mỗi agent + benchmark tạo một file log riêng, bao gồm:
    - Tất cả user turns và agent responses
    - Recall questions và agent answers (kèm expected + score)
    - Token usage mỗi lượt
    """

    def __init__(self, log_dir: Path, agent_name: str, benchmark_name: str) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_agent = agent_name.lower().replace(" ", "_")
        safe_bench = benchmark_name.lower().replace(" ", "_")
        self.log_file = self.log_dir / f"{safe_bench}_{safe_agent}_{timestamp}.md"
        self.json_file = self.log_dir / f"{safe_bench}_{safe_agent}_{timestamp}.json"

        self._md_lines: list[str] = []
        self._json_entries: list[dict[str, Any]] = []

        # Write header
        self._md_lines.append(f"# Chat Log: {agent_name} — {benchmark_name}")
        self._md_lines.append(f"")
        self._md_lines.append(f"> Thời gian chạy: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._md_lines.append(f"")

    def log_conversation_start(self, conv_id: str, user_id: str) -> None:
        self._md_lines.append(f"---")
        self._md_lines.append(f"")
        self._md_lines.append(f"## Conversation: `{conv_id}` (user: `{user_id}`)")
        self._md_lines.append(f"")

    def log_turn(
        self,
        conv_id: str,
        turn_index: int,
        user_msg: str,
        agent_response: str,
        tokens_used: int,
        prompt_tokens: int,
    ) -> None:
        # Markdown log
        self._md_lines.append(f"### Turn {turn_index + 1}")
        self._md_lines.append(f"")
        self._md_lines.append(f"**👤 User:**")
        self._md_lines.append(f"> {user_msg}")
        self._md_lines.append(f"")
        self._md_lines.append(f"**🤖 Agent:**")
        self._md_lines.append(f"> {agent_response}")
        self._md_lines.append(f"")
        self._md_lines.append(f"*Tokens — agent: {tokens_used}, prompt: {prompt_tokens}*")
        self._md_lines.append(f"")

        # JSON log
        self._json_entries.append({
            "type": "turn",
            "conv_id": conv_id,
            "turn_index": turn_index,
            "user_message": user_msg,
            "agent_response": agent_response,
            "tokens_used": tokens_used,
            "prompt_tokens": prompt_tokens,
        })

    def log_recall_question(
        self,
        conv_id: str,
        question: str,
        expected: list[str],
        agent_answer: str,
        recall_score: float,
        quality_score: float,
        tokens_used: int,
        prompt_tokens: int,
    ) -> None:
        # Determine which expected items were found
        answer_lower = agent_answer.lower()
        found = [e for e in expected if e.lower() in answer_lower]
        missed = [e for e in expected if e.lower() not in answer_lower]

        # Markdown log
        self._md_lines.append(f"### 🔍 Recall Question (cross-session)")
        self._md_lines.append(f"")
        self._md_lines.append(f"**❓ Question:**")
        self._md_lines.append(f"> {question}")
        self._md_lines.append(f"")
        self._md_lines.append(f"**🤖 Agent Answer:**")
        self._md_lines.append(f"> {agent_answer}")
        self._md_lines.append(f"")
        self._md_lines.append(f"**📊 Expected:** {', '.join(expected)}")
        if found:
            self._md_lines.append(f"- ✅ Found: {', '.join(found)}")
        if missed:
            self._md_lines.append(f"- ❌ Missed: {', '.join(missed)}")
        self._md_lines.append(f"- Recall score: **{recall_score:.1%}**")
        self._md_lines.append(f"- Quality score: **{quality_score:.1%}**")
        self._md_lines.append(f"- *Tokens — agent: {tokens_used}, prompt: {prompt_tokens}*")
        self._md_lines.append(f"")

        # JSON log
        self._json_entries.append({
            "type": "recall",
            "conv_id": conv_id,
            "question": question,
            "expected_contains": expected,
            "agent_answer": agent_answer,
            "found": found,
            "missed": missed,
            "recall_score": recall_score,
            "quality_score": quality_score,
            "tokens_used": tokens_used,
            "prompt_tokens": prompt_tokens,
        })

    def log_summary(self, row: BenchmarkRow) -> None:
        self._md_lines.append(f"---")
        self._md_lines.append(f"")
        self._md_lines.append(f"## 📊 Tổng kết Benchmark")
        self._md_lines.append(f"")
        self._md_lines.append(f"| Chỉ số | Giá trị |")
        self._md_lines.append(f"|--------|---------|")
        self._md_lines.append(f"| Agent tokens only | {row.agent_tokens_only} |")
        self._md_lines.append(f"| Prompt tokens processed | {row.prompt_tokens_processed} |")
        self._md_lines.append(f"| Cross-session recall | {row.recall_score:.1%} |")
        self._md_lines.append(f"| Response quality | {row.response_quality:.1%} |")
        self._md_lines.append(f"| Memory growth (bytes) | {row.memory_growth_bytes} |")
        self._md_lines.append(f"| Compactions | {row.compactions} |")
        self._md_lines.append(f"")

    def flush(self) -> Path:
        """Ghi tất cả log ra file và trả về đường dẫn."""
        # Write markdown
        self.log_file.write_text("\n".join(self._md_lines), encoding="utf-8")

        # Write JSON
        self.json_file.write_text(
            json.dumps(self._json_entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return self.log_file


# ===================================================================
# Helpers
# ===================================================================

def load_conversations(path: Path) -> list[dict[str, Any]]:
    """Read JSON conversations from disk."""

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def recall_points(answer: str, expected: list[str]) -> float:
    """Return 0 / 0.5 / 1 depending on how many expected facts appear.

    - All expected items found  → 1.0
    - Some found                → 0.5
    - None found                → 0.0
    """

    if not expected:
        return 1.0

    answer_lower = answer.lower()
    hits = sum(1 for e in expected if e.lower() in answer_lower)

    if hits == len(expected):
        return 1.0
    if hits > 0:
        return 0.5
    return 0.0


def heuristic_quality(answer: str, expected: list[str]) -> float:
    """Lightweight quality score for offline mode.

    Combines recall ratio with a length/structure bonus:
    - 60% weight on recall ratio (fraction of expected found)
    - 20% weight on length adequacy (not too short)
    - 20% weight on structure (has bullet points or formatting)
    """

    if not expected:
        return 1.0

    answer_lower = answer.lower()

    # Recall ratio
    hits = sum(1 for e in expected if e.lower() in answer_lower)
    recall_ratio = hits / len(expected)

    # Length adequacy (at least 30 chars is considered adequate)
    length_score = min(1.0, len(answer) / 30.0)

    # Structure bonus (bullet points, markdown)
    structure_score = 0.0
    if "-" in answer or "•" in answer or "**" in answer:
        structure_score = 1.0
    elif ":" in answer:
        structure_score = 0.5

    return 0.6 * recall_ratio + 0.2 * length_score + 0.2 * structure_score


# ===================================================================
# Benchmark runner
# ===================================================================

def run_agent_benchmark(
    agent_name: str,
    agent,
    conversations: list[dict[str, Any]],
    config,
    logger: ChatLogger | None = None,
) -> BenchmarkRow:
    """Evaluate one agent over many conversations.

    Steps:
    1. Feed all turns to the agent in their original threads.
    2. Track ``agent tokens only`` and ``prompt tokens processed``.
    3. Ask recall questions in a *fresh* thread (cross-session test).
    4. Compute average recall and quality.
    5. Record memory file growth and compaction count.
    6. Log all chat interactions to the logger.
    """

    total_agent_tokens = 0
    total_prompt_tokens = 0
    all_recall_scores: list[float] = []
    all_quality_scores: list[float] = []
    total_compactions = 0

    user_id = "benchmark_user"

    for conv in conversations:
        conv_user_id = conv.get("user_id", user_id)
        thread_id = conv["id"]
        turns = conv["turns"]

        if logger:
            logger.log_conversation_start(thread_id, conv_user_id)

        # Feed all turns
        for i, turn in enumerate(turns):
            result = agent.reply(conv_user_id, thread_id, turn)
            tokens_used = result.get("tokens_used", 0)
            prompt_tokens = result.get("prompt_tokens", 0)
            total_agent_tokens += tokens_used
            total_prompt_tokens += prompt_tokens

            if logger:
                logger.log_turn(
                    conv_id=thread_id,
                    turn_index=i,
                    user_msg=turn,
                    agent_response=result.get("response", ""),
                    tokens_used=tokens_used,
                    prompt_tokens=prompt_tokens,
                )

        # Track compaction for this thread
        total_compactions += agent.compaction_count(thread_id)

        # Ask recall questions in a FRESH thread
        recall_qs = conv.get("recall_questions", [])
        recall_thread = f"{thread_id}_recall"

        for rq in recall_qs:
            question = rq["question"]
            expected = rq["expected_contains"]

            result = agent.reply(conv_user_id, recall_thread, question)
            answer = result.get("response", "")
            tokens_used = result.get("tokens_used", 0)
            prompt_tokens = result.get("prompt_tokens", 0)

            total_agent_tokens += tokens_used
            total_prompt_tokens += prompt_tokens

            r_score = recall_points(answer, expected)
            q_score = heuristic_quality(answer, expected)
            all_recall_scores.append(r_score)
            all_quality_scores.append(q_score)

            if logger:
                logger.log_recall_question(
                    conv_id=thread_id,
                    question=question,
                    expected=expected,
                    agent_answer=answer,
                    recall_score=r_score,
                    quality_score=q_score,
                    tokens_used=tokens_used,
                    prompt_tokens=prompt_tokens,
                )

    # Memory growth
    memory_bytes = 0
    if hasattr(agent, "memory_file_size"):
        # Use the last user_id from conversations
        last_user_id = conversations[-1].get("user_id", user_id) if conversations else user_id
        memory_bytes = agent.memory_file_size(last_user_id)

    avg_recall = sum(all_recall_scores) / len(all_recall_scores) if all_recall_scores else 0.0
    avg_quality = sum(all_quality_scores) / len(all_quality_scores) if all_quality_scores else 0.0

    row = BenchmarkRow(
        agent_name=agent_name,
        agent_tokens_only=total_agent_tokens,
        prompt_tokens_processed=total_prompt_tokens,
        recall_score=round(avg_recall, 3),
        response_quality=round(avg_quality, 3),
        memory_growth_bytes=memory_bytes,
        compactions=total_compactions,
    )

    if logger:
        logger.log_summary(row)
        logger.flush()

    return row


# ===================================================================
# Output formatting
# ===================================================================

def format_rows(rows: list[BenchmarkRow]) -> str:
    """Print a tabulated markdown table."""

    headers = [
        "Agent",
        "Agent tokens only",
        "Prompt tokens processed",
        "Cross-session recall",
        "Response quality",
        "Memory growth (bytes)",
        "Compactions",
    ]

    table_data = []
    for r in rows:
        table_data.append([
            r.agent_name,
            r.agent_tokens_only,
            r.prompt_tokens_processed,
            f"{r.recall_score:.1%}",
            f"{r.response_quality:.1%}",
            r.memory_growth_bytes,
            r.compactions,
        ])

    return tabulate(table_data, headers=headers, tablefmt="github")


# ===================================================================
# Main
# ===================================================================

def main() -> None:
    """Run both benchmark suites and print comparison tables."""

    config = load_config(Path(__file__).resolve().parent.parent)
    log_dir = config.base_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)

    # ---- Standard Benchmark ----
    print("=" * 72)
    print("  STANDARD BENCHMARK  (data/conversations.json)")
    print("=" * 72)

    std_convs = load_conversations(config.data_dir / "conversations.json")

    # Clean state between runs
    state_dir = config.state_dir
    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    baseline_std = BaselineAgent(config=config, force_offline=True)
    advanced_std = AdvancedAgent(config=config, force_offline=True)

    logger_baseline_std = ChatLogger(log_dir, "Baseline", "Standard Benchmark")
    logger_advanced_std = ChatLogger(log_dir, "Advanced", "Standard Benchmark")

    row_baseline_std = run_agent_benchmark(
        "Baseline", baseline_std, std_convs, config, logger=logger_baseline_std,
    )
    row_advanced_std = run_agent_benchmark(
        "Advanced", advanced_std, std_convs, config, logger=logger_advanced_std,
    )

    print()
    print(format_rows([row_baseline_std, row_advanced_std]))
    print()
    print(f"  📁 Logs saved to: {log_dir}")
    print(f"     - {logger_baseline_std.log_file.name}")
    print(f"     - {logger_advanced_std.log_file.name}")
    print()

    # ---- Long-Context Stress Benchmark ----
    print("=" * 72)
    print("  LONG-CONTEXT STRESS BENCHMARK  (data/advanced_long_context.json)")
    print("=" * 72)

    stress_convs = load_conversations(config.data_dir / "advanced_long_context.json")

    # Clean state for stress test
    if state_dir.exists():
        shutil.rmtree(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    baseline_stress = BaselineAgent(config=config, force_offline=True)
    advanced_stress = AdvancedAgent(config=config, force_offline=True)

    logger_baseline_stress = ChatLogger(log_dir, "Baseline", "Stress Benchmark")
    logger_advanced_stress = ChatLogger(log_dir, "Advanced", "Stress Benchmark")

    row_baseline_stress = run_agent_benchmark(
        "Baseline", baseline_stress, stress_convs, config, logger=logger_baseline_stress,
    )
    row_advanced_stress = run_agent_benchmark(
        "Advanced", advanced_stress, stress_convs, config, logger=logger_advanced_stress,
    )

    print()
    print(format_rows([row_baseline_stress, row_advanced_stress]))
    print()
    print(f"  📁 Logs saved to: {log_dir}")
    print(f"     - {logger_baseline_stress.log_file.name}")
    print(f"     - {logger_advanced_stress.log_file.name}")
    print()

    # ---- Summary ----
    print("=" * 72)
    print("  ANALYSIS SUMMARY")
    print("=" * 72)
    print()
    print("Standard benchmark:")
    print(f"  - Baseline recall: {row_baseline_std.recall_score:.1%}")
    print(f"  - Advanced recall: {row_advanced_std.recall_score:.1%}")
    print(f"  - Advanced memory file: {row_advanced_std.memory_growth_bytes} bytes")
    print()
    print("Stress benchmark:")
    print(f"  - Baseline prompt tokens: {row_baseline_stress.prompt_tokens_processed}")
    print(f"  - Advanced prompt tokens: {row_advanced_stress.prompt_tokens_processed}")
    print(f"  - Advanced compactions:   {row_advanced_stress.compactions}")
    print(f"  - Prompt savings:         "
          f"{row_baseline_stress.prompt_tokens_processed - row_advanced_stress.prompt_tokens_processed} tokens")
    print()
    print(f"📁 Tất cả chat logs được lưu tại: {log_dir}")
    print()


if __name__ == "__main__":
    main()
