"""Success envelope: { "data": T, "meta": { "request_id", "next_cursor"? } }."""
from __future__ import annotations

from typing import Generic, TypeVar

from fastapi import Request
from pydantic import BaseModel, ConfigDict

from .errors import request_id_of

T = TypeVar("T")


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    next_cursor: str | None = None


class Envelope(BaseModel, Generic[T]):
    """Use as response_model=Envelope[SomeContractModel] so OpenAPI shows the real shape."""

    model_config = ConfigDict(extra="forbid")
    data: T
    meta: Meta | None = None


def ok(request: Request, data: T, *, next_cursor: str | None = None) -> Envelope[T]:
    return Envelope[T](
        data=data, meta=Meta(request_id=request_id_of(request), next_cursor=next_cursor)
    )
