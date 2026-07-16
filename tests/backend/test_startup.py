"""Tests for fail-fast startup validation (Step 17, ``app/startup.py``)."""

import pytest

from app.config import Settings
from app.startup import StartupValidationError, validate_settings


@pytest.fixture
def model_file(tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"gguf")
    return model


def make_settings(model_file, **overrides) -> Settings:
    """Settings with a valid baseline; ``_env_file=None`` keeps any local
    .env from bleeding into the test."""
    values = {"model_path": str(model_file), **overrides}
    return Settings(_env_file=None, **values)


def test_valid_settings_produce_no_problems(model_file):
    problems, _ = validate_settings(make_settings(model_file))
    assert problems == []


def test_missing_model_file_is_actionable(model_file, tmp_path):
    settings = make_settings(tmp_path / "nope.gguf")
    problems, _ = validate_settings(settings)
    [problem] = problems
    assert "MODEL_PATH" in problem
    assert "download_model" in problem


def test_bad_database_url_is_reported(model_file):
    problems, _ = validate_settings(
        make_settings(model_file, database_url="not a url at all ::")
    )
    assert any("DATABASE_URL" in p for p in problems)


def test_non_postgres_database_url_is_reported(model_file):
    problems, _ = validate_settings(
        make_settings(model_file, database_url="sqlite:///audit.db")
    )
    assert any("postgresql" in p for p in problems)


def test_numeric_bounds_are_enforced(model_file):
    settings = make_settings(
        model_file,
        llm_context_size=0,
        llm_max_tokens=0,
        llm_temperature=9.5,
        port=99_999,
        agent_workers=0,
        audit_max_queue_size=0,
        llm_max_queue_depth=-1,
        agent_max_steps=-2,
    )
    problems, _ = validate_settings(settings)
    for marker in (
        "LLM_CONTEXT_SIZE",
        "LLM_MAX_TOKENS",
        "LLM_TEMPERATURE",
        "PORT",
        "AGENT_WORKERS",
        "AUDIT_MAX_QUEUE_SIZE",
        "LLM_MAX_QUEUE_DEPTH",
        "AGENT_MAX_STEPS",
    ):
        assert any(marker in p for p in problems), marker


def test_invalid_redaction_regex_is_reported(model_file):
    settings = make_settings(
        model_file, audit_redaction_patterns=["(unclosed", r"\d+"]
    )
    problems, _ = validate_settings(settings)
    [problem] = [p for p in problems if "AUDIT_REDACTION_PATTERNS" in p]
    assert "(unclosed" in problem


def test_unknown_retention_table_is_reported(model_file):
    settings = make_settings(
        model_file, audit_retention_overrides={"nope": 3, "agent_events": -1}
    )
    problems, _ = validate_settings(settings)
    assert any("unknown table 'nope'" in p for p in problems)
    assert any("agent_events" in p and ">= 0" in p for p in problems)


def test_all_problems_are_collected_into_one_error(model_file, tmp_path):
    settings = make_settings(
        tmp_path / "nope.gguf",
        database_url="sqlite:///x.db",
        llm_context_size=-5,
    )
    problems, _ = validate_settings(settings)
    assert len(problems) >= 3
    error = StartupValidationError(problems)
    message = str(error)
    # One actionable message listing every problem.
    assert f"{len(problems)} problem(s)" in message
    for problem in problems:
        assert problem in message


def test_missing_static_dir_is_a_warning_not_a_problem(model_file, tmp_path):
    problems, warnings = validate_settings(
        make_settings(model_file), static_dir=tmp_path / "static"
    )
    assert problems == []
    assert any("build_frontend" in w for w in warnings)


def test_incomplete_static_dir_warns_about_the_bundle(model_file, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "assets").mkdir()
    problems, warnings = validate_settings(
        make_settings(model_file), static_dir=static
    )
    assert problems == []
    assert any("index.html" in w for w in warnings)
