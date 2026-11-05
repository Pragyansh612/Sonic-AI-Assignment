from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class BankDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_name: str
    account_number: str
    bank: str
    ifsc: str
    swift_code: str


class Policies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tds: str
    bank_charges: str
    extensions: str
    disputes: str
    working_hours: str


class OrganizationOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    address: str
    accounts_contact_name: str
    accounts_email: EmailStr | str
    phone: str
    default_currency: str
    accepted_currencies: list[str]
    payment_terms: str
    payment_methods: list[str]
    bank_details: BankDetails
    policies: Policies
