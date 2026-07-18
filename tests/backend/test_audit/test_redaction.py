"""Tests for audit redaction (Step 17, ``app/audit/redaction.py``): the
pattern library, custom patterns, and the producer-side hookup that keeps
unredacted text out of the audit queue entirely."""

import pytest

from app.audit.redaction import REPLACEMENT, Redactor
from app.audit.service import AuditService


@pytest.fixture
def redactor() -> Redactor:
    return Redactor()


@pytest.mark.parametrize(
    "secret",
    [
        "sk-abc123DEF456ghi789jkl",  # OpenAI-style key
        "AKIAIOSFODNN7EXAMPLE",  # AWS access key id
        "ghp_16C7e42F292c6912E7710c838347Ae178B4a",  # GitHub token
        "xoxb-1234567890-abcdefghij",  # Slack token
        "Bearer abcdef0123456789abcdef",  # Authorization header value
        "api_key=super-secret-value-9000",  # key=value assignment
    ],
)
def test_builtin_patterns_mask_wellknown_secrets(redactor, secret):
    text = f"please use {secret} to call the service"
    redacted = redactor.redact(text)
    assert REPLACEMENT in redacted
    for token in secret.split()[-1:]:  # the secret material itself
        assert token not in redacted


def test_private_key_blocks_are_masked(redactor):
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEA7bq0\n"
        "-----END RSA PRIVATE KEY-----"
    )
    redacted = redactor.redact(f"here: {pem} thanks")
    assert "MIIEowIBAAKCAQEA7bq0" not in redacted
    assert redacted == f"here: {REPLACEMENT} thanks"


def test_ordinary_text_is_untouched(redactor):
    text = "Summarize the Q3 sales figures for the northwest region."
    assert redactor.redact(text) == text


def test_none_and_empty_are_passed_through(redactor):
    assert redactor.redact(None) is None
    assert redactor.redact("") == ""


def test_custom_pii_patterns_apply_on_top_of_defaults():
    redactor = Redactor(extra_patterns=[r"\b\d{3}-\d{2}-\d{4}\b"])  # US SSN
    redacted = redactor.redact("ssn 123-45-6789 and key sk-abc123DEF456ghi789jkl")
    assert "123-45-6789" not in redacted
    assert "sk-abc123DEF456ghi789jkl" not in redacted


def test_invalid_custom_pattern_raises_at_construction():
    with pytest.raises(Exception):
        Redactor(extra_patterns=["(unclosed"])


# -- producer-side hookup ---------------------------------------------------------


async def test_service_redacts_prompt_fields_before_enqueueing():
    """The queued event already holds redacted text — the original never
    reaches the queue, the consumer, or the database."""
    service = AuditService(redactor=Redactor())  # consumer never started
    service.record_prompt_request(
        "r-1",
        "my key is sk-abc123DEF456ghi789jkl please",
        reviewed_prompt="my key is sk-abc123DEF456ghi789jkl please",
    )
    service.record_prompt_response(
        "r-1",
        llm_output="you said sk-abc123DEF456ghi789jkl",
        final_output="you said sk-abc123DEF456ghi789jkl",
    )

    request_event = service._queue.get_nowait()
    assert request_event.raw_prompt == f"my key is {REPLACEMENT} please"
    assert request_event.reviewed_prompt == f"my key is {REPLACEMENT} please"
    response_event = service._queue.get_nowait()
    assert response_event.llm_output == f"you said {REPLACEMENT}"
    assert response_event.final_output == f"you said {REPLACEMENT}"


async def test_service_without_redactor_stores_text_verbatim():
    service = AuditService()  # redaction disabled (the default)
    service.record_prompt_request("r-1", "key sk-abc123DEF456ghi789jkl")
    event = service._queue.get_nowait()
    assert event.raw_prompt == "key sk-abc123DEF456ghi789jkl"


async def test_redacted_prompt_lands_redacted_in_the_database(audit_db):
    """Step 17 verification: a prompt containing a fake API key is stored
    redacted in prompt_requests when redaction is enabled."""
    import uuid

    from sqlalchemy import select

    from app.audit import db
    from app.audit.models import PromptRequest

    request_id = f"r-{uuid.uuid4().hex[:12]}"
    service = AuditService(redactor=Redactor())
    service.start()
    try:
        service.record_prompt_request(
            request_id, "call it with sk-abc123DEF456ghi789jkl please"
        )
        await service.flush()
        async with db.session_scope() as session:
            row = (
                await session.execute(
                    select(PromptRequest).where(
                        PromptRequest.request_id == request_id
                    )
                )
            ).scalar_one()
        assert row.raw_prompt == f"call it with {REPLACEMENT} please"
        assert "sk-abc123DEF456ghi789jkl" not in row.raw_prompt
    finally:
        await service.close()
