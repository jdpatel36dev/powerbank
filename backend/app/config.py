from __future__ import annotations

import pathlib
import tomllib
from functools import cache
from typing import Dict

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Plan(BaseModel):
    code: str
    amount_major_units: int
    duration_minutes: int


class PricingTable(BaseModel):
    """Lookup table linking plans to charging durations."""

    currency: str = Field(default="INR", description="ISO-4217 currency code")
    plans: Dict[str, Plan] = Field(
        default_factory=dict, description="Plan code -> Plan definition"
    )

    def lookup_plan(self, plan_code: str) -> Plan:
        try:
            return self.plans[plan_code]
        except KeyError as exc:
            raise ValueError(f"No pricing rule configured for plan '{plan_code}'") from exc


class Settings(BaseSettings):
    """Application configuration loaded from environment variables / files."""

    razorpay_key_id: str = Field(..., env="RAZORPAY_KEY_ID")
    razorpay_key_secret: str = Field(..., env="RAZORPAY_KEY_SECRET")
    razorpay_webhook_secret: str = Field(..., env="RAZORPAY_WEBHOOK_SECRET")
    public_base_url: str = Field(
        default="http://localhost:8000",
        description="Public URL used to compose callback URLs in dev",
    )
    callback_path: str = Field(
        default="/pay/success",
        description="Path appended to public_base_url for Razorpay callbacks.",
    )
    mqtt_host: str = Field(default="localhost")
    mqtt_port: int = Field(default=1883)
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = Field(default="powerbank")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def pricing(self) -> PricingTable:
        return load_pricing_table()


@cache
def load_pricing_table() -> PricingTable:
    project_root = pathlib.Path(__file__).resolve().parents[1]
    pricing_path = project_root / "config" / "pricing.toml"
    data = tomllib.loads(pricing_path.read_text())
    currency = data.get("currency", "INR")
    plans_raw = data.get("plans", {})
    plans = {
        code: Plan(
            code=code,
            amount_major_units=int(details["amount"]),
            duration_minutes=int(details["duration"]),
        )
        for code, details in plans_raw.items()
    }
    if not plans:
        raise ValueError("No plans configured in pricing.toml")
    return PricingTable(currency=currency, plans=plans)



