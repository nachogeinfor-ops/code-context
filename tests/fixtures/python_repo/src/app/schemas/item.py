"""Pydantic schemas for Item — request / response shapes."""

from datetime import datetime

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class ItemRead(BaseModel):
    id: int
    title: str
    description: str | None
    owner_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
