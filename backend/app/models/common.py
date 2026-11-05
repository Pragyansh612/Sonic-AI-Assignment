"""Shared response helpers for money fields."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.money import format_money


class MoneyField(BaseModel):
    model_config = ConfigDict(frozen=True)

    minor: int = Field(description="Integer minor units (paise/cents)")
    currency: str
    formatted: str

    @classmethod
    def from_minor(cls, minor: int, currency: str) -> MoneyField:
        return cls(
            minor=minor,
            currency=currency,
            formatted=format_money(minor, currency),
        )
