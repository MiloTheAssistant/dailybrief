#!/usr/bin/env python3
"""Tests for fetch_proton_folder.py.

Smoke tests for the Bridge-backed Proton folder fetcher. Mock the
protonmail_tool.py subprocess calls and assert the fetcher's JSON
output shape, sender filtering, snippet truncation, and untrusted-
input handling (no raw HTML in snippets).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
FETCH = SCRIPTS / "fetch_proton_folder.py"

sys.path.insert(0, str(SCRIPTS))

import fetch_proton_folder  # noqa: E402


# ─── Fixtures ────────────────────────────────────────────────────────────────


SAMPLE_SEARCH_OUTPUT = """\
UID: 144
Date: Tue, 30 Jun 2026 14:43:02 -0400
From: Interactive Brokers <noresponse@email.interactivebrokers.com>
To: satoshi@coindexter.co
Subject: The Dollar, Inflation, and AI

UID: 145
Date: Thu, 25 Jun 2026 00:11:51 -0400
From: Interactive Brokers <noresponse@email.interactivebrokers.com>
To: satoshi@coindexter.co
Subject: Connect ChatGPT, Grok, or Claude to an IBKR Account

UID: 130
Date: Thu, 18 Jun 2026 18:40:04 -0400
From: Ross Givens <rossg@e.stocksurgedaily.com>
To: satoshi@coindexter.co
Subject: Live Now: These stocks are showing all the right signs
"""


SAMPLE_BODY_IB = """\
Your Daily Traders' Insight - June 30, 2026

body, table, td, a {
-webkit-text-size-adjust: 100%;
-ms-text-size-adjust: 100%;
}
table, td {
mso-table-lspace: 0pt;
mso-table-rspace: 0pt;
}

Your Daily Traders' Insight - June 30, 2026

TRADERS' INSIGHT:

Carrying On with the Japanese Yen
Today marks the end of the second quarter. We'd like to focus on the
Japanese yen and its ramifications for US stocks. Contributed By:
Steve Sosnick. The full article continues for several paragraphs with
detailed market analysis and trading recommendations for the coming
week. This is a long body that should be truncated at 200 chars in the
snippet, so the test will only see the first 200 chars of cleaned text.
"""


@pytest.fixture
def mock_bridge(monkeypatch):
    """Mock the protonmail_tool.py subprocess calls.

    Returns a function that lets each test register responses for
    specific argv patterns (search vs read) and yields the call list
    so tests can assert which commands were issued.
    """
    responses = {}
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        for pattern, response in responses.items():
            if pattern in cmd_str:
                if isinstance(response, Exception):
                    raise response
                from subprocess import CompletedProcess
                return CompletedProcess(
                    args=cmd, returncode=0,
                    stdout=response, stderr="",
                )
        # Default: empty success
        from subprocess import CompletedProcess
        return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    return {"responses": responses, "calls": calls}


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_search_parses_envelope_format():
    """Verify the search-output parser extracts UID/Date/From/To/Subject."""
    envelopes = fetch_proton_folder._parse_search_output(SAMPLE_SEARCH_OUTPUT)
    assert len(envelopes) == 3
    assert envelopes[0]["uid"] == "144"
    assert envelopes[0]["subject"] == "The Dollar, Inflation, and AI"
    assert envelopes[1]["uid"] == "145"
    assert envelopes[2]["from"] == "Ross Givens <rossg@e.stocksurgedaily.com>"


def test_extract_sender_email_pulls_address_from_angle_brackets():
    assert fetch_proton_folder._extract_sender_email(
        "Interactive Brokers <noresponse@email.interactivebrokers.com>"
    ) == "noresponse@email.interactivebrokers.com"
    assert fetch_proton_folder._extract_sender_email(
        "bare@example.com"
    ) == "bare@example.com"
    assert fetch_proton_folder._extract_sender_email("") == ""


def test_allowlist_filters_to_matching_senders():
    envelopes = fetch_proton_folder._parse_search_output(SAMPLE_SEARCH_OUTPUT)
    filtered = fetch_proton_folder._filter_by_sender(
        envelopes, allowlist=["email.interactivebrokers.com"], blocklist=None,
    )
    assert len(filtered) == 2
    for env in filtered:
        assert "email.interactivebrokers.com" in env["from"]


def test_blocklist_excludes_specific_senders():
    envelopes = fetch_proton_folder._parse_search_output(SAMPLE_SEARCH_OUTPUT)
    filtered = fetch_proton_folder._filter_by_sender(
        envelopes, allowlist=None,
        blocklist=["e.stocksurgedaily.com"],
    )
    assert len(filtered) == 2
    for env in filtered:
        assert "e.stocksurgedaily.com" not in env["from"]


def test_recency_filter_drops_old_envelopes():
    envelopes = fetch_proton_folder._parse_search_output(SAMPLE_SEARCH_OUTPUT)
    # 36h ago; UID 144 is 06-30 14:43 EDT (= 18:43 UTC).
    # UID 145 is 06-25, UID 130 is 06-18.
    # If "now" is mocked to 07-01 16:47 UTC, 36h cutoff is 06-30 04:47 UTC.
    # Only UID 144 should pass.
    import datetime
    real_datetime = fetch_proton_folder.datetime
    fixed_now = datetime.datetime(2026, 7, 1, 16, 47, 0,
                                  tzinfo=datetime.timezone.utc)
    with mock.patch.object(fetch_proton_folder, "datetime",
                          wraps=real_datetime) as mock_dt:
        mock_dt.now.return_value = fixed_now
        filtered = fetch_proton_folder._filter_by_recency(envelopes, 36)
    assert len(filtered) == 1
    assert filtered[0]["uid"] == "144"


def test_make_snippet_truncates_at_word_boundary():
    body = ("Carrying On with the Japanese Yen Today marks the end of "
            "the second quarter and what a quarter it has been")
    snippet = fetch_proton_folder._make_snippet(body, 30)
    assert len(snippet) <= 35  # ellipsis adds a few chars
    assert snippet.endswith("...")


def test_extract_text_skips_css_as_text_preamble():
    """The IB emails render CSS as bare text. Verify we strip it."""
    body = SAMPLE_BODY_IB
    cleaned = fetch_proton_folder._extract_text_from_mime_concat(body)
    # The first lines should NOT be CSS rules like "body, table, td, a {"
    assert not cleaned.startswith("body,")
    assert not cleaned.startswith("table, td {")
    # The real content "TRADERS' INSIGHT" or "Carrying On" should appear.
    assert "TRADERS' INSIGHT" in cleaned or "Carrying On" in cleaned


def test_post_clean_truncates_to_real_article():
    """The IB body has subject lines, blank lines, then the article.
    _post_clean should drop the boilerplate and keep the article."""
    body = (
        "Your Daily Traders' Insight - June 30, 2026\n"
        "\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n"
        "Your Daily Traders' Insight - June 30, 2026\n"
        "\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n"
        "TRADERS' INSIGHT:\n"
        "\n"
        "Carrying On with the Japanese Yen\n"
        "Today marks the end of the second quarter.\n"
        "Contributed By: Steve Sosnick\n"
    )
    cleaned = fetch_proton_folder._post_clean(body)
    # Should start with the marker, not the subject line.
    assert not cleaned.startswith("Your Daily")
    assert "TRADERS' INSIGHT" in cleaned
    assert "Carrying On" in cleaned
    # Repeated subject lines should be gone.
    assert cleaned.count("Your Daily Traders' Insight") <= 1


def test_post_clean_collapses_blank_lines():
    body = "First line\n\n\n\n\n\nSecond line\n\n\n\n\nThird line"
    cleaned = fetch_proton_folder._post_clean(body)
    # No more than 2 consecutive newlines anywhere.
    assert "\n\n\n" not in cleaned
    assert "First line" in cleaned
    assert "Third line" in cleaned


def test_post_clean_preserves_plain_text():
    """A normal plain-text body should pass through unchanged."""
    body = "This is a normal newsletter.\n\nIt has paragraphs.\n\nBest, Editor"
    cleaned = fetch_proton_folder._post_clean(body)
    assert cleaned == body


def test_snippet_contains_no_raw_html():
    """The fetcher's snippet must be plain text — no <tag> markup."""
    # Use a body that's purely HTML (no pre-CSS preamble) so the
    # CSS-skip path doesn't fire. The tag-stripper should still get
    # rid of all markup and leave just the prose.
    body_with_html = (
        "<html><head></head>"
        "<body><h1>Today's Markets</h1>"
        "<p>Stocks rallied on news from the Fed. <b>Read more.</b></p>"
        "</body></html>"
    )
    cleaned = fetch_proton_folder._extract_text_from_mime_concat(body_with_html)
    assert "<" not in cleaned
    assert ">" not in cleaned
    # Real content is there
    assert "Today's Markets" in cleaned
    assert "Stocks rallied" in cleaned


def test_end_to_end_json_shape(mock_bridge, capsys):
    """Smoke test: full invocation against a mocked Bridge."""
    mock_bridge["responses"]["search"] = SAMPLE_SEARCH_OUTPUT
    mock_bridge["responses"]["read"] = SAMPLE_BODY_IB

    with mock.patch.object(sys, "argv",
                           ["fetch_proton_folder.py",
                            "--sender-allowlist", "email.interactivebrokers.com",
                            "--since-hours", "240"]):
        rc = fetch_proton_folder.main()

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["folder"] == "Folders/DailyBriefs"
    assert payload["count"] == 2
    for env in payload["envelopes"]:
        assert "id" in env
        assert "subject" in env
        assert "sender" in env
        assert "date" in env
        assert "snippet" in env
        # Snippet should not contain raw HTML.
        assert "<" not in env["snippet"]
        # Snippet should be at most 200 chars + the "..." marker.
        assert len(env["snippet"]) <= 204
