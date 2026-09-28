"""Pydantic request/response schemas."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatAttachment(BaseModel):
    kind: str = Field(..., description="text | image | audio")
    filename: str = ""
    caption: str = ""
    transcript: str = ""
    text: str = ""
    data_base64: str = ""


class ChatRequest(BaseModel):
    user_id: str = Field(default="anonymous", description="external user id / account")
    user_name: str = ""
    session_id: str = "default"
    text: str = ""
    attachments: list[ChatAttachment] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    interaction_id: int
    kind: str = Field(..., description="thumb | rating | correction | text")
    value: Any = Field(default=None, description="up/down for thumb, 1-5 for rating")
    text: str = Field(default="", description="correction text or free-text feedback")
    user_id: Optional[str] = None


class DocumentIn(BaseModel):
    title: str
    text: str = ""
    source: str = ""
    modality: str = "text"
    mime: str = "text/plain"
    meta: dict = Field(default_factory=dict)


class FactIn(BaseModel):
    statement: str
    source_interaction_id: Optional[int] = None
    evidence: dict = Field(default_factory=dict)
    auto_active: bool = Field(default=False, description="admin: make live immediately")


class UserIn(BaseModel):
    ext_id: str
    name: str = ""


class ResolveIn(BaseModel):
    decision: str = Field(default="resolved", description="resolved | dismissed")
    note: str = ""


class SearchRequest(BaseModel):
    text: str
    user_id: Optional[str] = Field(default=None,
                                   description="scope memory results to this user's profile")
    kinds: list[str] = Field(default_factory=lambda: ["document", "fact", "memory"],
                             description="which sources to search")
    top_k: int = Field(default=8, ge=1, le=50)
