#!/usr/bin/env python3
"""fetch_proton_folder.py — list envelopes + snippets from a named Proton folder.

Companion to fetch_proton_mail.py. Whereas fetch_proton_mail.py is the
canonical "list envelopes" helper used by the enrich path, this script
is purpose-built for the DailyBriefs workflow: it pulls recent envelopes
from a configured folder, extracts plain-text snippets, and applies
sender filters so promotional / non-actionable content stays out of
the DFB.

Source of truth: Proton Mail Bridge over local IMAP (see
~/repos/CodexMasterSkills/protonmail-hermes-skill.md). The Proton
Bridge credentials come from ~/.config/codex_skills/protonmail-bridge.env
(Bridge-generated mailbox password, NOT the Proton account password).

Output JSON to stdout for downstream consumption:
    {
        "folder": "Folders/DailyBriefs",
        "count": 3,
        "fetched_at": "2026-07-01T...",
        "envelopes": [
            {
                "id": "144",
                "subject": "...",
                "sender": "noresponse@email.interactivebrokers.com",
                "date": "2026-06-30 ...",
                "is_seen": false,
                "snippet": "First 200 chars of plain-text body..."
            },
            ...
        ]
    }

The snippet is plain-text, HTML-stripped, and capped at 200 chars.
Email content is untrusted input — the DFB treats the snippet as
data, not instructions. The snippet is intentionally NOT a markdown
rendered block; it's a raw string for the LLM to interpret.

Args:
    --folder FOLDER       Folder name (default: Folders/DailyBriefs)
    --since-hours N       Only envelopes newer than N hours (default: 18)
    --limit N             Max envelopes to return (default: 10)
    --sender-allowlist    Comma-separated sender substring matches
                          (e.g. "email.interactivebrokers.com"). If set,
                          only matching senders are returned.
    --sender-blocklist    Comma-separated sender substring matches to
                          exclude. Applied AFTER allowlist.
    --snippet-chars N     Max chars in body snippet (default: 200)
    --json                Output JSON (default; flag exists for clarity)
    --plain               Output human-readable plain text (for debugging)

Exit codes:
    0 = success
    1 = protonmail_tool.py call failed
    2 = protonmail_tool.py not on PATH
    3 = parse error
    4 = snippet extraction failed (body too malformed even for plain text)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser


# Default folder is the curated DailyBriefs staging area on the
# coindexter.co Proton account. Override with --folder for other use
# cases.
DEFAULT_FOLDER = "Folders/DailyBriefs"
DEFAULT_SNIPPET_CHARS = 200
DEFAULT_SINCE_HOURS = 36


@dataclass
class FolderEnvelope:
    id: str
    subject: str
    sender: str
    date: str
    is_seen: bool
    snippet: str = ""


def call_protonmail_tool(folder: str) -> tuple[list[dict], str]:
    """Run protonmail_tool.py search --query "all" and return (envelopes, raw).

    Returns a list of envelope dicts (from the tool's structured output)
    AND the raw stdout, so callers can use whichever is more convenient.
    The protonmail_tool.py search subcommand prints results in a fixed
    format (UID: / Date: / From: / To: / Subject: / blank line), so
    we parse it ourselves rather than depending on JSON output.
    """
    script = "/Volumes/BotCentral/Users/milo/.codex/skills/protonmail/scripts/protonmail_tool.py"
    cmd = ["python3", script, "search", "--mailbox", folder, "--query", "all"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=30,
        )
    except FileNotFoundError:
        print("fetch_proton_folder: protonmail_tool.py not found", file=sys.stderr)
        sys.exit(2)
    except subprocess.CalledProcessError as e:
        print(
            f"fetch_proton_folder: search failed rc={e.returncode}: "
            f"{e.stderr.strip()[:200]}",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("fetch_proton_folder: search timed out after 30s", file=sys.stderr)
        sys.exit(1)
    return _parse_search_output(result.stdout), result.stdout


def _parse_search_output(raw: str) -> list[dict]:
    """Parse protonmail_tool.py's search output into envelope dicts.

    The tool emits groups of 5 lines per envelope, separated by blank
    lines:
        UID: 144
        Date: Tue, 30 Jun 2026 14:43:02 -0400
        From: Interactive Brokers <noresponse@email.interactivebrokers.com>
        To: satoshi@coindexter.co
        Subject: The Dollar, Inflation, and AI

    Groups are separated by blank lines. End-of-output is reached when
    a line is neither a known key nor blank.
    """
    envelopes = []
    current: dict = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line:
            if current:
                envelopes.append(current)
                current = {}
            continue
        m = re.match(r"^(UID|Date|From|To|Subject):\s*(.*)$", line)
        if m:
            current[m.group(1).lower()] = m.group(2).strip()
        # Anything else: skip silently. The tool occasionally leaks
        # log lines (e.g. "  ⏳ ...") that we don't want as envelope data.
    if current:
        envelopes.append(current)
    return envelopes


def _extract_sender_email(sender_field: str) -> str:
    """Pull the email address out of a 'Name <addr@host>' field.

    Returns the bare address if no angle brackets, else whatever's
    inside them. Used for allowlist/blocklist substring matching.
    """
    m = re.search(r"<([^>]+)>", sender_field)
    if m:
        return m.group(1)
    return sender_field.strip()


def _filter_by_sender(
    envelopes: list[dict],
    allowlist: list[str] | None,
    blocklist: list[str] | None,
) -> list[dict]:
    """Apply allowlist then blocklist. Empty allowlist = allow all."""
    out = []
    for env in envelopes:
        sender = _extract_sender_email(env.get("from", ""))
        if allowlist:
            if not any(sub in sender for sub in allowlist):
                continue
        if blocklist:
            if any(sub in sender for sub in blocklist):
                continue
        out.append(env)
    return out


def _filter_by_recency(envelopes: list[dict], since_hours: int) -> list[dict]:
    """Drop envelopes older than since_hours ago.

    Parses the Date: line, which is in RFC2822 format. Falls back to
    keeping the envelope if the date is unparseable (don't silently
    drop — the user can decide what to do with the unparseable ones).
    """
    if since_hours <= 0:
        return envelopes
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out = []
    for env in envelopes:
        date_str = env.get("date", "")
        try:
            from email.utils import parsedate_to_datetime
            ts = parsedate_to_datetime(date_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts < cutoff:
                continue
        except (ValueError, TypeError):
            # Unparseable — keep it. Don't silently drop.
            pass
        out.append(env)
    return out


def _read_body_plaintext(folder: str, uid: str) -> str:
    """Fetch the plain-text body of a single message. Returns "" on error.

    The protonmail_tool.py `read` subcommand returns headers + body
    separated by a `--- Body ---` line. The body may be a
    multipart/alternative concatenation (text/plain + text/html), in
    which case we use the email module to extract just the text/plain
    part. If only text/html is available, we strip tags and return
    that. If we can't parse the MIME structure, we fall back to the
    raw body (better than nothing, but the snippet quality will be
    poor).
    """
    script = "/Volumes/BotCentral/Users/milo/.codex/skills/protonmail/scripts/protonmail_tool.py"
    cmd = ["python3", script, "read", "--mailbox", folder, "--uid", uid]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""
    stdout = result.stdout
    if "--- Body ---" not in stdout:
        return ""
    body = stdout.split("--- Body ---", 1)[1].strip()
    return _extract_text_from_mime_concat(body)


def _extract_text_from_mime_concat(body: str) -> str:
    """Walk a concatenated MIME body and return the best plain-text part.

    The protonmail_tool.py `read` output joins all MIME parts of a
    multipart message with blank lines. This means a single body string
    can contain a text/plain part, a text/html part, and (sometimes)
    an inline CSS-as-text preamble (the IBKR Traders' Insight emails
    are particularly bad about this — the marketing HTML's CSS reset
    block is rendered as bare text rather than inside a <style> tag,
    which the upstream html_to_text() can't strip).

    We try to identify the real text content in this order:

      1. If the body has MIME boundaries, parse it as a multipart
         message and return the first text/plain part.
      2. Skip any leading CSS-as-text preamble (lines that look
         like CSS — have `{}` and `;` and start with a CSS selector).
         The real content starts after the preamble.
      3. If the body looks like HTML, strip tags + <style>/<script>
         blocks and return the result.
      4. Return the body as-is.
    """
    # 1. Try MIME parsing if there are boundaries.
    if re.search(r"^--+[A-Za-z0-9_=.-]+$", body, re.MULTILINE):
        try:
            msg = BytesParser(policy=policy.default).parsebytes(
                body.encode("utf-8", errors="ignore")
            )
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    return _post_clean(part.get_content().strip())
        except Exception:
            pass

    # 2. Skip CSS-as-text preamble. A CSS line is one where the line
    # has more `;` or `{}` than prose. We accumulate CSS-looking
    # lines and drop them, returning what comes after.
    lines = body.splitlines()
    last_css_line = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Heuristics for a CSS line:
        # - Contains a CSS selector pattern: starts with a word, then
        #   has `.class` or `#id` or `tag{` or contains `;` with
        #   `property: value;` shape
        if (
            "{" in stripped and "}" in stripped
            or re.match(r"^[.#\w][\w\-,\s:#.]*\s*\{", stripped)
            or re.match(r"^[\w-]+\s*:\s*[^;]+;\s*$", stripped)
        ):
            last_css_line = i
            continue
        # If the line has multiple `;` and is short, also CSS.
        if stripped.count(";") >= 2 and len(stripped) < 200:
            last_css_line = i
            continue
        # If the line is a CSS comment
        if stripped.startswith("/*") or stripped.startswith("//"):
            last_css_line = i
            continue
    if last_css_line >= 0:
        # Drop everything up to and including the last CSS line.
        # The first non-CSS line is where real content starts.
        body = "\n".join(lines[last_css_line + 1:]).strip()

    # 3. If still HTML, strip tags + style/script blocks.
    if body.lstrip().startswith("<"):
        body = re.sub(r"<style\b[^>]*>.*?</style>", " ", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<script\b[^>]*>.*?</script>", " ", body, flags=re.DOTALL | re.IGNORECASE)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()

    return _post_clean(body)


def _post_clean(body: str) -> str:
    """Post-extraction cleanup applied to all snippet bodies.

    Newsletter bodies from the IBKR Daily Traders' Insight (and
    similar marketing emails) include:
      - Repeated subject lines ("Your Daily Traders' Insight - June 30, 2026")
        at the top, after the CSS preamble, and before the article body.
      - Runs of 10+ blank lines between blocks.
      - The real prose at the END of the body, after the boilerplate.

    This pass:
      1. Detects the "real content marker" (TRADERS' INSIGHT:,
         Contributed By:, or the first paragraph after a marker line).
      2. Collapses runs of blank lines to a single blank line.
      3. Prefers text after the LAST occurrence of a marker (the
         article body comes after the boilerplate).
    """
    if not body:
        return body

    # Known content markers. If we see any of these, the real
    # article starts at the FIRST marker (not the last — the
    # "Contributed By:" attribution line is *after* the article
    # body, so the last-marker logic chops off the actual prose).
    markers = [
        "TRADERS' INSIGHT:",         # IBKR
        "MARKETS COMMENTARY:",
        "Dear Reader,",
        "Editor's Note:",
    ]

    # Find the FIRST occurrence of any marker. The article body
    # starts at this line and runs until the next "Contributed By:"
    # or end of body.
    first_marker_idx = -1
    for marker in markers:
        for i, line in enumerate(body.splitlines()):
            if marker in line:
                first_marker_idx = i
                break
        if first_marker_idx >= 0:
            break

    if first_marker_idx >= 0:
        body = "\n".join(body.splitlines()[first_marker_idx:]).strip()

    # Now find the FIRST "Contributed By:" line AFTER the marker
    # (it's the attribution and the boilerplate that follows is
    # not part of the article). If found, clip everything from
    # that line onward.
    contributed_idx = -1
    for i, line in enumerate(body.splitlines()):
        if "Contributed By:" in line:
            contributed_idx = i
            break
    if contributed_idx >= 0:
        body = "\n".join(body.splitlines()[:contributed_idx]).strip()

    # Collapse runs of 3+ blank lines to a single blank line.
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # If the body still has lots of repeated subject headers (the
    # marker-based path didn't find anything), drop any line that
    # matches the subject pattern. This is a fallback.
    subject_pattern = re.compile(
        r"^Your Daily.*?(Insight|Brief|Newsletter).*?$",
        re.IGNORECASE,
    )
    lines = [line for line in body.splitlines() if not subject_pattern.match(line.strip())]
    body = "\n".join(lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return body


def _make_snippet(body: str, max_chars: int) -> str:
    """Truncate to max_chars, ending on a word boundary if possible."""
    if len(body) <= max_chars:
        return body
    truncated = body[:max_chars]
    # If we cut mid-word, back up to the last space.
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.7:  # don't cut too much
        truncated = truncated[:last_space]
    return truncated.rstrip() + "..."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", default=DEFAULT_FOLDER,
                        help=f"Folder name (default: {DEFAULT_FOLDER})")
    parser.add_argument("--since-hours", type=int, default=DEFAULT_SINCE_HOURS,
                        help=f"Only envelopes newer than N hours (default: {DEFAULT_SINCE_HOURS}). "
                             "36h covers the IBKR Daily Traders' Insight which "
                             "fires on weekday mornings US time and may be older "
                             "than 18h by the time the DFB cron runs.")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max envelopes to return (default: 10)")
    parser.add_argument("--sender-allowlist", default=None,
                        help="Comma-separated sender substring matches (e.g. "
                             "'email.interactivebrokers.com')")
    parser.add_argument("--sender-blocklist", default=None,
                        help="Comma-separated sender substring matches to exclude")
    parser.add_argument("--snippet-chars", type=int, default=DEFAULT_SNIPPET_CHARS,
                        help=f"Max chars in body snippet (default: {DEFAULT_SNIPPET_CHARS})")
    parser.add_argument("--plain", action="store_true",
                        help="Human-readable output (default: JSON)")
    args = parser.parse_args()

    allowlist = [s.strip() for s in (args.sender_allowlist or "").split(",") if s.strip()]
    blocklist = [s.strip() for s in (args.sender_blocklist or "").split(",") if s.strip()]

    # 1. Pull envelope list.
    envelopes, _ = call_protonmail_tool(args.folder)
    if not envelopes:
        if args.plain:
            print(f"# 0 envelope(s) from {args.folder!r}")
        else:
            print(json.dumps({
                "folder": args.folder,
                "count": 0,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "envelopes": [],
            }, indent=2))
        return 0

    # 2. Filter by sender (allowlist + blocklist) and recency.
    filtered = _filter_by_sender(envelopes, allowlist, blocklist)
    filtered = _filter_by_recency(filtered, args.since_hours)

    # 3. Sort by date descending, take top N.
    def _date_key(env: dict) -> str:
        return env.get("date", "")
    filtered.sort(key=_date_key, reverse=True)
    filtered = filtered[: args.limit]

    # 4. Fetch body snippet for each. Skip the snippet read if
    # --snippet-chars is 0 (useful for testing or for the LLM to do
    # its own body fetch later).
    results: list[FolderEnvelope] = []
    for env in filtered:
        body = ""
        if args.snippet_chars > 0:
            body = _read_body_plaintext(args.folder, env.get("uid", ""))
        snippet = _make_snippet(body, args.snippet_chars)
        sender = _extract_sender_email(env.get("from", ""))
        results.append(FolderEnvelope(
            id=env.get("uid", ""),
            subject=env.get("subject", ""),
            sender=sender,
            date=env.get("date", ""),
            is_seen=False,  # search doesn't surface flag info; LLM can ignore
            snippet=snippet,
        ))

    # 5. Emit JSON (or plain) envelope.
    if args.plain:
        print(f"# {len(results)} envelope(s) from {args.folder!r}")
        for e in results:
            print(f"[{e.id}] {e.subject} — {e.sender}")
            if e.snippet:
                print(f"    {e.snippet[:120]}{'...' if len(e.snippet) > 120 else ''}")
    else:
        print(json.dumps({
            "folder": args.folder,
            "count": len(results),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "envelopes": [asdict(e) for e in results],
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
