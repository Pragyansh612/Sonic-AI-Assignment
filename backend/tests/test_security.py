from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security import reject_mongo_operators


def test_reject_dollar_keys() -> None:
    with pytest.raises(HTTPException) as exc:
        reject_mongo_operators({"$gt": 1})
    assert exc.value.status_code == 400


def test_reject_dotted_keys() -> None:
    with pytest.raises(HTTPException):
        reject_mongo_operators({"a.b": 1})


def test_nested_allowed_structure() -> None:
    reject_mongo_operators({"contact_email": "a@b.com"})
