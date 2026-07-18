"""User-facing identity fields pinned into the injected chat summary (Step 20).

The five identity fields — name, age, occupation, personality, interests —
form the "minimum viable persona" that must survive any summary reset. They
are stored *outside* the LLM-maintained rolling buffer: the pipeline prepends
:meth:`IdentityStore.format_block` to the rolling summary at injection time
(via :func:`compose_summary`), and the summarizer never sees the block, so
re-summarization can never drop or distort it.

Defaults come from the ``IDENTITY_*`` settings; runtime edits via
``PUT /api/identity`` replace the in-memory values and are lost on restart —
consistent with the rest of the live state. No locking: everything runs on
the single event loop, and :meth:`replace` swaps the dict atomically.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checkers
    from app.config import Settings

# Field order is presentation order in the injected block.
IDENTITY_FIELDS: tuple[str, ...] = (
    "name",
    "age",
    "occupation",
    "personality",
    "interests",
)

_LABELS = {
    "name": "Name",
    "age": "Age",
    "occupation": "Occupation",
    "personality": "Personality",
    "interests": "Interests",
}


class IdentityStore:
    """In-memory holder of the five identity fields."""

    def __init__(self, **fields: str) -> None:
        unknown = set(fields) - set(IDENTITY_FIELDS)
        if unknown:
            raise ValueError(f"unknown identity fields: {sorted(unknown)}")
        self._fields = {
            name: (fields.get(name) or "").strip() for name in IDENTITY_FIELDS
        }

    @classmethod
    def from_settings(cls, settings: "Settings") -> "IdentityStore":
        """Build the store from the ``IDENTITY_*`` settings."""
        return cls(
            name=settings.identity_name,
            age=settings.identity_age,
            occupation=settings.identity_occupation,
            personality=settings.identity_personality,
            interests=settings.identity_interests,
        )

    def get(self) -> dict[str, str]:
        """A copy of the five fields."""
        return dict(self._fields)

    def replace(self, values: dict[str, str]) -> dict[str, str]:
        """Full-replace semantics: every field is taken from ``values``
        (missing keys become empty), whitespace stripped. Returns the new
        fields."""
        self._fields = {
            name: (values.get(name) or "").strip() for name in IDENTITY_FIELDS
        }
        return self.get()

    def format_block(self) -> str:
        """The pinned identity text, one ``Label: value`` line per non-empty
        field in presentation order; empty when no field is set."""
        lines = [
            f"{_LABELS[name]}: {value}"
            for name, value in self._fields.items()
            if value
        ]
        return "\n".join(lines)


def compose_summary(identity_block: str, rolling: str, *, max_chars: int) -> str:
    """Combine the pinned identity block and the rolling summary under one
    character budget.

    The identity block is never truncated (the per-field 200-char cap keeps
    it small); when the combination is over budget the *rolling* tail is cut,
    or dropped entirely when the identity leaves no room.
    """
    if not identity_block and not rolling:
        return ""
    if not rolling:
        return identity_block
    if not identity_block:
        if len(rolling) > max_chars:
            return rolling[: max_chars - 1] + "…"
        return rolling
    combined = f"{identity_block}\n\n{rolling}"
    if len(combined) <= max_chars:
        return combined
    budget = max_chars - len(identity_block) - 2  # 2 = the "\n\n" separator
    if budget <= 1:
        return identity_block
    return f"{identity_block}\n\n{rolling[: budget - 1]}…"
