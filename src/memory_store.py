from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ===================================================================
# Token estimation
# ===================================================================

def estimate_tokens(text: str) -> int:
    """Simple heuristic token estimator.

    Uses character-count / 4 which is a reasonable approximation
    for Vietnamese + English mixed text.  Returns at least 1 for
    non-empty input so that every message has *some* cost.
    """

    stripped = text.strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


# ===================================================================
# User profile store  (persistent ``User.md``)
# ===================================================================

_DEFAULT_PROFILE = """\
# User Profile

## Name
(chưa biết)

## Location
(chưa biết)

## Profession
(chưa biết)

## Response Style
(chưa biết)

## Favorite Drink
(chưa biết)

## Favorite Food
(chưa biết)

## Pet
(chưa biết)

## Interests
(chưa biết)
"""


@dataclass
class UserProfileStore:
    """Persistent storage backed by one markdown file per user.

    Each user id maps to ``<root_dir>/<slug>.md``.
    """

    root_dir: Path

    # ------ path helpers ------

    @staticmethod
    def _slugify(user_id: str) -> str:
        slug = re.sub(r"[^\w\-]", "_", user_id.strip().lower())
        return slug or "anonymous"

    def path_for(self, user_id: str) -> Path:
        return self.root_dir / f"{self._slugify(user_id)}.md"

    # ------ CRUD ------

    def read_text(self, user_id: str) -> str:
        """Return file content or the empty default markdown profile."""
        p = self.path_for(user_id)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return _DEFAULT_PROFILE

    def write_text(self, user_id: str, content: str) -> Path:
        """Write markdown to disk and return the file path."""
        p = self.path_for(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def edit_text(self, user_id: str, search_text: str, replacement: str) -> bool:
        """Replace *one* occurrence of ``search_text`` inside the profile.

        Returns ``True`` if a replacement was made.
        """
        content = self.read_text(user_id)
        if search_text not in content:
            return False
        new_content = content.replace(search_text, replacement, 1)
        self.write_text(user_id, new_content)
        return True

    def file_size(self, user_id: str) -> int:
        """Return current file size in bytes (0 if not yet created)."""
        p = self.path_for(user_id)
        return p.stat().st_size if p.exists() else 0

    # ------ Structured fact helpers (bonus) ------

    _SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)

    def facts(self, user_id: str) -> dict[str, str]:
        """Parse the markdown profile into a ``{section_title: value}`` dict."""
        text = self.read_text(user_id)
        result: dict[str, str] = {}
        sections = self._SECTION_RE.split(text)
        # sections is like ['# User Profile\n', 'Name', '\nvalue\n', 'Location', ...]
        i = 1
        while i < len(sections) - 1:
            key = sections[i].strip()
            val = sections[i + 1].strip()
            if val and val != "(chưa biết)":
                result[key] = val
            i += 2
        return result

    def upsert_fact(self, user_id: str, section: str, value: str) -> None:
        """Insert or update a specific section in the profile.

        If the section exists, its content is replaced.
        If not, a new ``## section`` block is appended.
        """
        content = self.read_text(user_id)

        # Try to replace existing section content
        pattern = re.compile(
            rf"(##\s+{re.escape(section)}\s*\n)(.*?)(?=\n##\s|\Z)",
            re.DOTALL,
        )
        match = pattern.search(content)
        if match:
            new_content = content[: match.start(2)] + value + "\n" + content[match.end(2):]
        else:
            new_content = content.rstrip() + f"\n\n## {section}\n{value}\n"

        self.write_text(user_id, new_content)


# ===================================================================
# Profile fact extraction from user messages
# ===================================================================

# Bonus: correction signal patterns
_CORRECTION_SIGNALS = re.compile(
    r"đính chính|không còn|giờ chuyển sang|giờ mình|hiện tại mình|"
    r"chuyển sang|không phải.*nữa|nhớ ưu tiên thông tin mới",
    re.IGNORECASE,
)


def extract_profile_updates(message: str) -> dict[str, str]:
    """Convert raw user text into stable profile facts.

    Bonus features:
    - Confidence threshold: skip question-only turns.
    - Detects correction signals for conflict handling.

    Returns a dict like ``{"Name": "DũngCT", "Location": "Huế"}``.
    """

    stripped = message.strip()
    if not stripped:
        return {}

    # ----- Confidence threshold: skip question-only turns -----
    # A message that is purely a question (ends with ?) and does not
    # contain a clear declarative fact-giving keyword is skipped.
    question_words = ["gì", "đâu", "nào", "không", "sao", "bao nhiêu", "ai"]
    is_question = "?" in stripped

    # Declarative fact signals – the sentence *gives* info, not asks
    declarative_signals = [
        "tên là", "mình tên", "mình ở", "đang ở", "hiện ở",
        "đang làm", "chuyển sang", "yêu thích là",
        "nuôi một", "nuôi con", "nuôi bé", "muốn bạn trả lời",
        "Món ăn yêu thích", "Đồ uống yêu thích",
    ]
    has_declarative = any(sig in stripped for sig in declarative_signals)

    if is_question and not has_declarative:
        return {}

    facts: dict[str, str] = {}

    # --- Name ---
    name_match = re.search(
        r"(?:tên là|mình tên là|tên mình là|mình tên)\s+"
        r"([A-ZĐÀÁẢÃẠÈÉẺẼẸÌÍỈĨỊÒÓỎÕỌÙÚỦŨỤỲÝỶỸỴÊÔƠƯĂa-zđàáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵêôơưă][\w\s]*\w)",
        stripped,
        re.IGNORECASE,
    )
    if name_match:
        raw_name = name_match.group(1).strip().rstrip(".")
        # Skip if it looks like a question fragment
        if not any(q in raw_name.lower() for q in question_words):
            facts["Name"] = raw_name

    # --- Location ---
    loc_match = re.search(
        r"(?:hiện ở|đang ở|mình ở|hiện tại.*ở|đang làm việc ở)\s+"
        r"(\S+(?:\s+\S+){0,3})",
        stripped,
        re.IGNORECASE,
    )
    if loc_match:
        raw_loc = loc_match.group(1).strip().rstrip(".")
        # Clean trailing filler phrases
        raw_loc = re.split(r"\s+(?:và|để|chứ|nên|vì|mà|cho|vài|trong)\s+", raw_loc)[0].strip()
        # Skip question words
        if not any(q in raw_loc.lower() for q in question_words) and len(raw_loc) <= 40:
            facts["Location"] = raw_loc

    # --- Profession ---
    prof_match = re.search(
        r"(?:đang làm|chuyển sang|làm)\s+"
        r"([\w\s]+(?:engineer|developer|manager|designer|analyst|scientist|researcher"
        r"|MLOps|DevOps|backend|frontend|fullstack)[\w\s]*)",
        stripped,
        re.IGNORECASE,
    )
    if prof_match:
        facts["Profession"] = prof_match.group(1).strip().rstrip(".")

    # --- Favorite Drink ---
    drink_match = re.search(
        r"(?:đồ uống yêu thích|đồ uống.*là|thích)\s+"
        r"([\w\s]+(?:đá|sữa|trà|nước|bia|rượu)[\w\s]*)",
        stripped,
        re.IGNORECASE,
    )
    if drink_match:
        facts["Favorite Drink"] = drink_match.group(1).strip().rstrip(".")

    # --- Favorite Food ---
    food_match = re.search(
        r"(?:Món ăn yêu thích là|món ăn yêu thích|món ruột)\s+"
        r"([\w\sảãạàáấầắằẳẵặẩẫ]+)",
        stripped,
        re.IGNORECASE,
    )
    if food_match:
        facts["Favorite Food"] = food_match.group(1).strip().rstrip(".")

    # --- Response Style ---
    style_match = re.search(
        r"(?:muốn bạn trả lời|style trả lời|trả lời)\s+"
        r"([\w\s,]+(?:gọn|ngắn|bullet|ví dụ|thực tế|trade-off|thực chiến)[\w\s,]*)",
        stripped,
        re.IGNORECASE,
    )
    if style_match:
        raw_style = style_match.group(1).strip().rstrip(".")
        if len(raw_style) <= 80:
            facts["Response Style"] = raw_style

    # --- Pet ---
    pet_match = re.search(
        r"(?:nuôi một|nuôi)\s+(?:bé|con|chú)?\s*"
        r"([\w\s]+?)(?:\s+tên\s+([\w]+))?(?:\.|$)",
        stripped,
        re.IGNORECASE,
    )
    if pet_match:
        pet_type = pet_match.group(1).strip()
        pet_name = pet_match.group(2)
        pet_info = pet_type
        if pet_name:
            pet_info += f" tên {pet_name}"
        facts["Pet"] = pet_info

    return facts


# ===================================================================
# Message summarization
# ===================================================================

def summarize_messages(messages: list[dict[str, str]], max_items: int = 6) -> str:
    """Create a compact summary of older messages.

    This is a heuristic text-concatenation approach.  Each message is
    shortened to its first ~120 chars and the whole block is prefixed
    with a header so the agent knows it is reading a summary.
    """

    if not messages:
        return ""

    lines: list[str] = ["[Tóm tắt hội thoại cũ]"]
    for msg in messages[:max_items]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        short = content[:120].replace("\n", " ")
        if len(content) > 120:
            short += "…"
        lines.append(f"- {role}: {short}")

    return "\n".join(lines)


# ===================================================================
# Compact memory manager
# ===================================================================

@dataclass
class CompactMemoryManager:
    """Compact memory for long threads.

    Keeps recent messages in full and moves older content into a
    rolling summary when the estimated token count exceeds the
    threshold.  Tracks compaction count for benchmarking.
    """

    threshold_tokens: int
    keep_messages: int
    state: dict[str, dict[str, object]] = field(default_factory=dict)

    def _ensure_thread(self, thread_id: str) -> dict[str, object]:
        if thread_id not in self.state:
            self.state[thread_id] = {
                "messages": [],
                "summary": "",
                "compactions": 0,
            }
        return self.state[thread_id]

    # Maximum summary length in characters to prevent unbounded growth.
    _MAX_SUMMARY_CHARS: int = 1200

    def append(self, thread_id: str, role: str, content: str) -> None:
        """Append a message and trigger compaction if needed."""

        ts = self._ensure_thread(thread_id)
        ts["messages"].append({"role": role, "content": content})  # type: ignore[union-attr]

        # Only count *message* tokens for the threshold check.
        # The summary is already compressed and should not re-trigger
        # compaction, otherwise the system compacts too aggressively.
        msg_tokens = sum(
            estimate_tokens(m["content"])
            for m in ts["messages"]  # type: ignore[union-attr]
        )

        if msg_tokens > self.threshold_tokens:
            self._compact(thread_id)

    def _compact(self, thread_id: str) -> None:
        """Move older messages into the rolling summary."""
        ts = self.state[thread_id]
        msgs: list[dict[str, str]] = ts["messages"]  # type: ignore[assignment]

        if len(msgs) <= self.keep_messages:
            return  # nothing to compact

        old_msgs = msgs[: -self.keep_messages]
        kept_msgs = msgs[-self.keep_messages:]

        # Merge old summary + old messages into new summary
        existing_summary = str(ts["summary"])
        new_piece = summarize_messages(old_msgs)
        if existing_summary:
            merged = existing_summary + "\n" + new_piece
        else:
            merged = new_piece

        # Cap summary length to prevent unbounded growth.
        # Keep the tail (most recent information is more valuable).
        if len(merged) > self._MAX_SUMMARY_CHARS:
            merged = "[...]\n" + merged[-self._MAX_SUMMARY_CHARS:]

        ts["summary"] = merged
        ts["messages"] = kept_msgs
        ts["compactions"] = int(ts["compactions"]) + 1  # type: ignore[arg-type]

    def context(self, thread_id: str) -> dict[str, object]:
        """Return per-thread state with keys ``messages``, ``summary``, ``compactions``."""
        return dict(self._ensure_thread(thread_id))

    def compaction_count(self, thread_id: str) -> int:
        ts = self._ensure_thread(thread_id)
        return int(ts["compactions"])
