"""Wire schema for the identity fields (Step 20)."""

from pydantic import BaseModel, Field


class Identity(BaseModel):
    """The five user-facing identity fields pinned into the internal chat
    summary.

    Used for both the GET response and the PUT request body: fields default
    to empty, so a PUT carries full-replace semantics — omitted fields are
    blanked.
    """

    name: str = Field("", max_length=200, description="Name.")
    age: str = Field("", max_length=200, description="Age.")
    occupation: str = Field("", max_length=200, description="Occupation.")
    personality: str = Field("", max_length=200, description="Personality.")
    interests: str = Field("", max_length=200, description="Interests.")
