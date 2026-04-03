"""
Testy jednostkowe: agent/ingestion/email_parser.py

Testowane komponenty:
    - ParsedEmail.from_string()  – parsowanie surowych wiadomości MIME
    - ParsedEmail.from_request() – budowanie z danych API
    - Ekstrakcja URL, SPF, nagłówków, hopów
"""
from __future__ import annotations

import pytest

from agent.ingestion.email_parser import ParsedEmail


# ─────────────────────────────────────────────────────────────────────────────
# Helpersy
# ─────────────────────────────────────────────────────────────────────────────

PLAIN_EML = """\
From: sender@example.com\r
To: recipient@example.com\r
Subject: Hello world\r
MIME-Version: 1.0\r
Content-Type: text/plain; charset=utf-8\r
\r
This is a simple plain text body.\
"""

MULTIPART_EML = """\
From: sender@example.com\r
To: recipient@example.com\r
Subject: Multipart test\r
MIME-Version: 1.0\r
Content-Type: multipart/alternative; boundary="boundary42"\r
\r
--boundary42\r
Content-Type: text/plain; charset=utf-8\r
\r
Plain text part.\r
--boundary42\r
Content-Type: text/html; charset=utf-8\r
\r
<html><body><p>HTML part with <a href="http://example.com/link">a link</a>.</p></body></html>\r
--boundary42--\r
"""

SPF_FAIL_EML = """\
From: spoofer@evil.com\r
To: victim@company.com\r
Subject: Fake\r
Authentication-Results: mx.company.com; spf=fail smtp.mailfrom=evil.com\r
MIME-Version: 1.0\r
Content-Type: text/plain\r
\r
Body.\
"""

SPF_PASS_EML = """\
From: legit@company.com\r
To: you@company.com\r
Subject: Legit\r
Authentication-Results: mx.company.com; spf=pass smtp.mailfrom=company.com\r
MIME-Version: 1.0\r
Content-Type: text/plain\r
\r
Body.\
"""

RECEIVED_HOPS_EML = """\
From: sender@example.com\r
To: r@example.com\r
Subject: Hops\r
Received: from mx1.example.com by mx2.example.com\r
Received: from smtp.example.com by mx1.example.com\r
Received: from client.example.com by smtp.example.com\r
MIME-Version: 1.0\r
Content-Type: text/plain\r
\r
Body.\
"""

ENCODED_SUBJECT_EML = """\
From: sender@example.com\r
To: r@example.com\r
Subject: =?UTF-8?B?UGlsbmU6IHdlcnlmaWt1aiBrb250bw==?=\r
MIME-Version: 1.0\r
Content-Type: text/plain\r
\r
Body.\
"""

REPLY_TO_EML = """\
From: bank@real-bank.com\r
Reply-To: attacker@gmail.com\r
To: customer@example.com\r
Subject: Important\r
MIME-Version: 1.0\r
Content-Type: text/plain\r
\r
Body.\
"""

URL_IN_TEXT_EML = """\
From: sender@example.com\r
To: r@example.com\r
Subject: Links\r
MIME-Version: 1.0\r
Content-Type: text/plain\r
\r
Visit http://example.com/page and also https://other.org/path?q=1 for details.\
"""


# ─────────────────────────────────────────────────────────────────────────────
# Testy: from_string
# ─────────────────────────────────────────────────────────────────────────────

class TestFromString:
    def test_basic_fields_populated(self):
        parsed = ParsedEmail.from_string(PLAIN_EML)
        assert parsed.from_addr == "sender@example.com"
        assert parsed.subject == "Hello world"
        assert parsed.plain_text.strip() == "This is a simple plain text body."

    def test_plain_text_is_captured(self):
        parsed = ParsedEmail.from_string(PLAIN_EML)
        assert "simple plain text body" in parsed.plain_text
        assert parsed.has_html is False

    def test_multipart_splits_plain_and_html(self):
        parsed = ParsedEmail.from_string(MULTIPART_EML)
        assert "Plain text part" in parsed.plain_text
        assert parsed.has_html is True

    def test_html_url_extracted(self):
        parsed = ParsedEmail.from_string(MULTIPART_EML)
        assert "http://example.com/link" in parsed.urls

    def test_plain_text_url_extracted(self):
        parsed = ParsedEmail.from_string(URL_IN_TEXT_EML)
        assert "http://example.com/page" in parsed.urls
        assert "https://other.org/path?q=1" in parsed.urls

    def test_spf_fail_detected(self):
        parsed = ParsedEmail.from_string(SPF_FAIL_EML)
        assert parsed.spf_result == "fail"

    def test_spf_pass_detected(self):
        parsed = ParsedEmail.from_string(SPF_PASS_EML)
        assert parsed.spf_result == "pass"

    def test_spf_none_when_missing(self):
        parsed = ParsedEmail.from_string(PLAIN_EML)
        assert parsed.spf_result in ("none", "")

    def test_received_hops_counted(self):
        parsed = ParsedEmail.from_string(RECEIVED_HOPS_EML)
        assert parsed.received_hops == 3

    def test_reply_to_extracted(self):
        parsed = ParsedEmail.from_string(REPLY_TO_EML)
        assert "attacker@gmail.com" in parsed.reply_to

    def test_encoded_subject_decoded(self):
        parsed = ParsedEmail.from_string(ENCODED_SUBJECT_EML)
        # Base64: "Pilne: weryfikuj konto"
        assert parsed.subject  # nie może być pustym stringiem
        assert "?" not in parsed.subject  # prawidłowo zdekodowany

    def test_raw_size_positive(self):
        parsed = ParsedEmail.from_string(PLAIN_EML)
        assert parsed.raw_size > 0

    def test_empty_string_returns_empty_parsed(self):
        parsed = ParsedEmail.from_string("")
        assert parsed.subject == ""
        assert parsed.plain_text == ""
        assert parsed.urls == []

    def test_no_attachment_flag_for_plain(self):
        parsed = ParsedEmail.from_string(PLAIN_EML)
        assert parsed.has_attachments is False


# ─────────────────────────────────────────────────────────────────────────────
# Testy: from_request
# ─────────────────────────────────────────────────────────────────────────────

class TestFromRequest:
    def test_basic_fields(self):
        parsed = ParsedEmail.from_request(
            sender="test@example.com",
            subject="Test subject",
            body="Hello body text",
        )
        assert parsed.from_addr == "test@example.com"
        assert parsed.subject == "Test subject"
        assert "Hello body text" in parsed.plain_text

    def test_html_detection(self):
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="HTML mail",
            body="<html><body><p>Content</p></body></html>",
        )
        assert parsed.has_html is True

    def test_plain_text_no_html_flag(self):
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="Plain",
            body="Just plain text with no tags",
        )
        assert parsed.has_html is False

    def test_urls_parameter_used(self):
        urls = ["http://example.com/one", "https://other.org/two"]
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="Links",
            body="See above",
            urls=urls,
        )
        assert "http://example.com/one" in parsed.urls
        assert "https://other.org/two" in parsed.urls

    def test_duplicate_urls_deduplicated(self):
        url = "http://example.com/repeated"
        parsed = ParsedEmail.from_request(
            sender="s@s.com",
            subject="Dup",
            body="",
            urls=[url, url, url],
        )
        assert parsed.urls.count(url) == 1

    def test_none_sender_handled(self):
        parsed = ParsedEmail.from_request(sender=None, subject="No sender", body="Body")
        assert isinstance(parsed.from_addr, str)
