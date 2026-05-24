import os, re, sys
from dataclasses import dataclass, field
import anthropic

VALID_ACTIONS = {"CLOSE THIS", "THIS NEEDS ATTENTION", "REVIEW AND MERGE THIS"}


@dataclass
class TriageResult:
    number: int
    item_type: str
    title: str
    action: str
    reason: str
    duplicate_of: int = None
    signals: list = field(default_factory=list)


_DUPE_KW = re.compile(
    r"(?:duplicate\s+of|dupe\s+of|same\s+as|superseded\s+by)\s+#(\d+)",
    re.IGNORECASE,
)
_CLOSE_KW = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
    re.IGNORECASE,
)


def detect_duplicate_signals(item, comments, pr_files, all_items):
    signals = []
    referenced_number = None
    title = (item.get("title") or "").lower()
    title_words = set(re.findall(r"\b\w{4,}\b", title))
    dupe_match = _DUPE_KW.search(item.get("body") or "")
    if dupe_match:
        signals.append("Explicit duplicate-of reference in description")
        referenced_number = int(dupe_match.group(1))
    close_match = _CLOSE_KW.search(item.get("body") or "")
    if close_match and not referenced_number:
        referenced_number = int(close_match.group(1))
    for comment in comments:
        c_body = comment.get("body") or ""
        if _DUPE_KW.search(c_body):
            signals.append("Comment flags this as a duplicate")
            m = _DUPE_KW.search(c_body)
            if m and not referenced_number:
                referenced_number = int(m.group(1))
            break
    for other in all_items:
        if other.get("number") == item.get("number"):
            continue
        other_title = (other.get("title") or "").lower()
        other_words = set(re.findall(r"\b\w{4,}\b", other_title))
        if len(title_words) >= 3 and title_words == other_words:
            signals.append("Near-exact title match with #" + str(other["number"]))
            if not referenced_number:
                referenced_number = other["number"]
            break
        if title_words and other_words:
            shared = title_words & other_words
            overlap = len(shared) / max(len(title_words), len(other_words))
            if overlap >= 0.75 and len(shared) >= 3:
                signals.append("High keyword overlap (" + str(int(overlap * 100)) + "%) with #" + str(other["number"]))
                if not referenced_number:
                    referenced_number = other["number"]
                break
    if pr_files:
        touched = {f["filename"] for f in pr_files}
        for other in all_items:
            if other.get("number") == item.get("number"):
                continue
            other_files = other.get("_pr_files", [])
            if not other_files:
                continue
            other_touched = {f["filename"] for f in other_files}
            overlap_files = touched & other_touched
            if len(overlap_files) >= 2:
                signals.append("Overlapping files with #" + str(other["number"]) + ": " + ", ".join(sorted(overlap_files)[:3]))
                if not referenced_number:
                    referenced_number = other["number"]
                break
    return signals, referenced_number


def _build_prompt(item, item_type, comments, pr_files, signals, referenced_number):
    number = item["number"]
    title = item.get("title", "(no title)")
    body = (item.get("body") or "(no description provided)").strip()[:3000]
    labels = ", ".join(lbl["name"] for lbl in item.get("labels", [])) or "none"
    created_at = item.get("created_at", "unknown")
    updated_at = item.get("updated_at", "unknown")
    if comments:
        clines = []
        for c in comments[-5:]:
            author = c.get("user", {}).get("login", "unknown")
            c_body = (c.get("body") or "").strip()[:500]
            clines.append("  [" + author + "]: " + c_body)
        comment_text = "\n".join(clines)
    else:
        comment_text = "  (no comments)"
    if pr_files:
        flines = []
        for f in pr_files[:15]:
            patch = (f.get("patch") or "")[:300]
            flines.append(
                "  " + f["filename"]
                + " (+" + str(f.get("additions", 0))
                + "/-" + str(f.get("deletions", 0)) + ")"
                + ("\n    " + patch if patch else "")
            )
        files_text = "\n".join(flines)
        if len(pr_files) > 15:
            files_text += "\n  ... and " + str(len(pr_files) - 15) + " more files"
    else:
        files_text = "  (not a PR or no files available)"
    signal_block = ""
    if signals:
        slines = "\n".join("  - " + s for s in signals)
        ref = ("\n  Referenced item: #" + str(referenced_number)) if referenced_number else ""
        signal_block = "\nDUPLICATE SIGNALS DETECTED (" + str(len(signals)) + "):\n" + slines + ref
    return "\n".join([
        "You are a senior open-source maintainer triaging a GitHub repository.",
        "Classify the following " + item_type + " into exactly ONE action category:",
        "",
        "  1. CLOSE THIS           - Duplicate, already resolved, stale, or not needed.",
        "  2. THIS NEEDS ATTENTION - Valid and unresolved; needs work or a decision.",
        "  3. REVIEW AND MERGE THIS - PR that is valid and looks ready to merge.",
        "",
        "---",
        item_type + " #" + str(number) + ": " + title,
        "Labels: " + labels,
        "Created: " + created_at + "  |  Updated: " + updated_at,
        "",
        "DESCRIPTION:",
        body,
        "",
        "RECENT COMMENTS:",
        comment_text,
        "",
        "CHANGED FILES (PRs only):",
        files_text,
        signal_block,
        "---",
        "",
        "RULES:",
        "- If duplicate signals >= 2: classify as CLOSE THIS.",
        "- Only REVIEW AND MERGE THIS for PRs with real, meaningful code changes.",
        "- Only CLOSE THIS with a clear specific reason (not just age).",
        "- Reference actual content from description, comments, or files.",
        "",
        "Respond EXACTLY in this format (no fences, no extra text):",
        "",
        "ACTION: <CLOSE THIS | THIS NEEDS ATTENTION | REVIEW AND MERGE THIS>",
        "REASON: <1-3 specific sentences>",
    ])


class Analyzer:
    MODEL = "claude-haiku-4-5"

    def __init__(self, api_key=None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
            sys.exit(1)
        self._client = anthropic.Anthropic(api_key=key)

    def analyze(self, item, item_type, comments, pr_files, all_items):
        signals, referenced_number = detect_duplicate_signals(item, comments, pr_files, all_items)
        prompt = _build_prompt(item, item_type, comments, pr_files, signals, referenced_number)
        message = self._client.messages.create(
            model=self.MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        action, reason = self._parse_response(raw)
        if len(signals) >= 2 and action != "CLOSE THIS":
            action = "CLOSE THIS"
            reason = (
                "Rule-based override: " + str(len(signals)) + " duplicate signals. "
                + "; ".join(signals[:2])
                + (" References #" + str(referenced_number) if referenced_number else "")
            )
        return TriageResult(
            number=item["number"],
            item_type=item_type,
            title=item.get("title", "(no title)"),
            action=action,
            reason=reason,
            duplicate_of=(referenced_number if action == "CLOSE THIS" and referenced_number else None),
            signals=signals,
        )

    def _parse_response(self, raw):
        action = "THIS NEEDS ATTENTION"
        reason = raw
        am = re.search(r"^ACTION:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
        rm = re.search(r"^REASON:\s*(.+?)(?:\n|$)", raw, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        if am:
            candidate = am.group(1).strip().upper()
            for v in VALID_ACTIONS:
                if v in candidate or candidate in v:
                    action = v
                    break
        if rm:
            reason = rm.group(1).strip()
        return action, reason
