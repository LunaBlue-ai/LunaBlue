"""Redaction of secrets and PII before audit rows are written (Step 17).

Per docs/Components/AUDIT.md ("encrypt or redact sensitive prompt data"), the
audit layer can mask obvious secrets — API keys, tokens, private keys — plus
any deployment-specific PII patterns before an event is enqueued. When
redaction is enabled the ``raw_prompt`` column stores the *redacted* text:
the trade-off (documented in docs/DataRetention.md) is that the original
input is unrecoverable from the audit record, which is exactly the point —
a leaked audit database must not be a credential store.

Redaction is regex-based and therefore best-effort: it catches well-known
token shapes and anything the configured patterns match, not every possible
secret. It runs on the producer side of :class:`~app.audit.service.AuditService`
(cheap, bounded regex work) so redacted text is all that ever sits in the
queue or reaches the database.
"""

import re
from collections.abc import Iterable

# Well-known secret shapes masked whenever redaction is enabled. Kept
# deliberately high-precision: false positives destroy audit value.
DEFAULT_SECRET_PATTERNS: tuple[str, ...] = (
    r"\bsk-[A-Za-z0-9_-]{16,}\b",  # OpenAI/Anthropic-style API keys
    r"\bAKIA[0-9A-Z]{16}\b",  # AWS access key ids
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",  # GitHub tokens
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",  # Slack tokens
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b",  # JWTs
    r"(?i)\bbearer\s+[a-z0-9._~+/=-]{16,}",  # Authorization: Bearer …
    # key=value / key: value assignments for obviously-secret key names.
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|secret|password|passwd)\b\s*[:=]\s*\S+",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
)

REPLACEMENT = "[REDACTED]"


class Redactor:
    """Compiled redaction pass applied to audited text fields.

    ``extra_patterns`` are deployment-specific regexes (PII formats, internal
    ticket ids, …) from ``AUDIT_REDACTION_PATTERNS``; they are applied after
    the built-in secret patterns. Invalid patterns raise ``re.error`` at
    construction time — startup validation reports them before boot completes.
    """

    def __init__(
        self,
        *,
        extra_patterns: Iterable[str] = (),
        include_defaults: bool = True,
        replacement: str = REPLACEMENT,
    ) -> None:
        sources: list[str] = []
        if include_defaults:
            sources.extend(DEFAULT_SECRET_PATTERNS)
        sources.extend(extra_patterns)
        self._patterns: list[re.Pattern[str]] = [re.compile(p) for p in sources]
        self._replacement = replacement

    def redact(self, text: str | None) -> str | None:
        """Return ``text`` with every configured pattern masked; None-safe."""
        if not text:
            return text
        for pattern in self._patterns:
            text = pattern.sub(self._replacement, text)
        return text
