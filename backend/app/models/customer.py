from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    customer_id: str
    name: str
    contact_name: str
    contact_email: EmailStr | str
    phone: str
    city: str
    country: str
    currency: str


class CustomerUpdateEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_email: EmailStr = Field(description="Validated email address")
