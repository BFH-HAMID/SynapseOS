"""Chat + feedback endpoints — the primary inference surface."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from synapseos.api.deps import get_db, get_engine, require_api_key
from synapseos.engine import SynapseEngine
from synapseos.schemas import ChatRequest, FeedbackRequest

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_api_key)])


@router.post("", summary="Chat: text + optional image/voice attachments")
def chat(req: ChatRequest, engine: SynapseEngine = Depends(get_engine)):
    if not req.text and not req.attachments:
        raise HTTPException(422, "provide text or at least one attachment")
    attachments = []
    for a in req.attachments:
        data = None
        if a.data_base64:
            try:
                data = base64.b64decode(a.data_base64)
            except Exception:
                raise HTTPException(422, f"invalid base64 in attachment {a.filename}")
        attachments.append({"kind": a.kind, "filename": a.filename, "caption": a.caption,
                            "transcript": a.transcript, "text": a.text, "data": data})
    return _chat(engine, req, attachments)


def _chat(engine, req, attachments):
    if req.user_name:
        from synapseos.learning.personalization import Personalization
        db = engine.db()
        try:
            Personalization.ensure_user(db, req.user_id, req.user_name)
            db.commit()
        finally:
            db.close()
    return engine.chat(req.user_id, req.session_id, req.text, attachments)


@router.post("/upload", summary="Chat with multipart file uploads (image/audio)")
async def chat_upload(
    payload: str = Form(..., description="JSON ChatRequest (without attachments)"),
    files: list[UploadFile] = File(default=[]),
    engine: SynapseEngine = Depends(get_engine),
):
    import json as _json

    try:
        req = ChatRequest(**_json.loads(payload))
    except Exception as e:
        raise HTTPException(422, f"invalid payload JSON: {e}")
    attachments = []
    for f in files:
        raw = await f.read()
        kind = "image" if (f.content_type or "").startswith("image/") else \
               "audio" if (f.content_type or "").startswith("audio/") else "text"
        if kind == "text" and raw:
            try:
                attachments.append({"kind": "text", "text": raw.decode("utf-8", "replace"),
                                    "filename": f.filename})
                continue
            except Exception:
                pass
        attachments.append({"kind": kind, "filename": f.filename or "upload",
                            "data": raw, "caption": "", "transcript": ""})
    return _chat(engine, req, attachments)


@router.post("/feedback", summary="Submit feedback (thumbs / rating / correction / text)")
def feedback(req: FeedbackRequest, engine: SynapseEngine = Depends(get_engine)):
    if req.kind not in ("thumb", "rating", "correction", "text"):
        raise HTTPException(422, "kind must be thumb|rating|correction|text")
    if req.kind == "thumb" and str(req.value).lower() not in ("up", "down"):
        raise HTTPException(422, "thumb value must be 'up' or 'down'")
    if req.kind == "rating":
        try:
            v = float(req.value)
            assert 1 <= v <= 5
        except Exception:
            raise HTTPException(422, "rating value must be a number 1-5")
    if req.kind == "correction" and not req.text.strip():
        raise HTTPException(422, "correction requires text")
    result = engine.feedback(req.interaction_id, req.kind, req.value, req.text, req.user_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/history", summary="Session history (short-term memory)")
def history(session_id: str = "default", user_id: str = "anonymous", limit: int = 20,
            engine: SynapseEngine = Depends(get_engine)):
    return {"session_id": session_id, "user_id": user_id,
            "messages": engine.sessions.history(f"s:{user_id}:{session_id}", limit=limit)}
