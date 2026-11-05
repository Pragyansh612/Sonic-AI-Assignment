from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class UploadResponse(BaseModel):
    statement_id: str
    filename: str
    row_count: int
    error_count: int
    parse_errors: list[dict[str, Any]]
    suggestion_count: int


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_numbers: list[str] | None = Field(
        default=None,
        description="Override suggested invoices; defaults to suggestion",
    )
    tds_mode: Literal["close_tds", "leave_open"] | None = None


class ChooseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_numbers: list[str] = Field(min_length=1)


class RejectResponse(BaseModel):
    suggestion_id: str
    status: str


class OpenInvoiceOut(BaseModel):
    invoice_number: str
    customer_id: str
    customer_name: str
    currency: str
    due_date: str
    outstanding: dict[str, Any]
    subtotal_minor: int
    total_minor: int
    tds_expected_payment_minor: int | None
