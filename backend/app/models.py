from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class CreateSessionRequest(BaseModel):
    plan_code: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    device_id: str = Field(
        default="bay-1",
        description="Identifier for the charging bay; used by the Raspberry Pi subscriber.",
    )
    callback_path: str | None = Field(
        default=None,
        description="Optional override for the callback path appended to the public base URL.",
    )
    customer_email: str | None = Field(default=None, description="Optional email for receipt.")
    customer_contact: str | None = Field(
        default=None, description="Optional phone number for receipt / notifications."
    )


class CreateSessionResponse(BaseModel):
    payment_link_url: HttpUrl
    payment_link_id: str
    plan_code: str
    amount_major_units: int
    currency: str
    duration_minutes: int



