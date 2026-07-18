"""Tests for the identity store and summary composition (Step 20)."""

import pytest

from app.config import Settings
from app.state.identity import IdentityStore, compose_summary

# -- IdentityStore -----------------------------------------------------------------


def test_format_block_orders_and_omits_empty_fields():
    store = IdentityStore(
        interests="cats, code",
        name="Luna",
        occupation="",
        personality="  curious  ",
    )
    assert store.format_block() == (
        "Name: Luna\nPersonality: curious\nInterests: cats, code"
    )


def test_format_block_is_empty_when_no_field_is_set():
    assert IdentityStore().format_block() == ""


def test_replace_is_full_replace_and_strips_whitespace():
    store = IdentityStore(name="Luna", age="7")
    result = store.replace({"name": "  Zed  ", "occupation": "pilot"})
    assert result == {
        "name": "Zed",
        "age": "",  # missing keys are blanked
        "occupation": "pilot",
        "personality": "",
        "interests": "",
    }
    assert store.get() == result


def test_get_returns_a_copy():
    store = IdentityStore(name="Luna")
    fields = store.get()
    fields["name"] = "mutated"
    assert store.get()["name"] == "Luna"


def test_unknown_field_names_are_rejected():
    with pytest.raises(ValueError, match="unknown identity fields"):
        IdentityStore(nickname="Lu")


def test_from_settings_maps_the_identity_settings():
    settings = Settings(
        identity_name="Luna",
        identity_age="7",
        identity_occupation="assistant",
        identity_personality="curious",
        identity_interests="cats",
        _env_file=None,
    )
    store = IdentityStore.from_settings(settings)
    assert store.get() == {
        "name": "Luna",
        "age": "7",
        "occupation": "assistant",
        "personality": "curious",
        "interests": "cats",
    }


# -- compose_summary ---------------------------------------------------------------


def test_compose_both_empty_is_empty():
    assert compose_summary("", "", max_chars=100) == ""


def test_compose_identity_only_passes_through():
    assert compose_summary("Name: Luna", "", max_chars=100) == "Name: Luna"


def test_compose_rolling_only_caps_defensively():
    assert compose_summary("", "short", max_chars=100) == "short"
    capped = compose_summary("", "x" * 200, max_chars=50)
    assert len(capped) == 50
    assert capped.endswith("…")


def test_compose_both_under_budget_joins_with_blank_line():
    assert compose_summary("Name: Luna", "rolling text", max_chars=100) == (
        "Name: Luna\n\nrolling text"
    )


def test_compose_over_budget_truncates_the_rolling_tail_never_identity():
    identity = "Name: Luna"
    combined = compose_summary(identity, "r" * 100, max_chars=50)
    assert len(combined) == 50
    assert combined.startswith("Name: Luna\n\n")
    assert combined.endswith("…")


def test_compose_tiny_budget_drops_rolling_entirely():
    identity = "Name: Luna"  # 10 chars; budget for rolling would be <= 1
    assert compose_summary(identity, "rolling", max_chars=12) == identity
