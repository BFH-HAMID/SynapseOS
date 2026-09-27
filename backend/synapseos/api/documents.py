"""Document ingestion endpoints (RAG corpus)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from synapseos.api.deps import get_db, get_engine, require_api_key
from synapseos.db.models import Document
from synapseos.engine import SynapseEngine
from synapseos.kb.knowledge_base import chunk_text
from synapseos.schemas import DocumentIn

router = APIRouter(tags=["documents"], dependencies=[Depends(require_api_key)])


@router.post("/documents", summary="Ingest a text document into the knowledge base")
def add_document(req: DocumentIn, db: Session = Depends(get_db),
                 engine: SynapseEngine = Depends(get_engine)):
    if not req.text.strip():
        raise HTTPException(422, "text required")
    doc = engine.kb.add_document(db, title=req.title, text=req.text, source=req.source,
                                 modality=req.modality, mime=req.mime, meta=req.meta)
    return {"id": doc.id, "title": doc.title, "chunks": len(chunk_text(req.text))}


@router.post("/documents/upload", summary="Ingest an uploaded file (txt/md text; images become captioned KB entries)")
async def upload_document(file: UploadFile = File(...), title: str = Form(""),
                          source: str = Form("upload"),
                          engine: SynapseEngine = Depends(get_engine),
                          db: Session = Depends(get_db)):
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "empty file")
    mime = file.content_type or "application/octet-stream"
    title = title or (file.filename or "untitled")
    if mime.startswith("image/"):
        item = engine.embedder.embed_image(raw, file.filename or "image", title)
        doc = engine.kb.add_document(db, title=title, text=item.text_repr, source=source,
                                     modality="image", mime=mime,
                                     meta={"caption": item.text_repr, **item.meta})
    elif mime.startswith("audio/"):
        item = engine.embedder.embed_audio(raw, file.filename or "audio")
        doc = engine.kb.add_document(db, title=title, text=item.text_repr, source=source,
                                     modality="audio", mime=mime, meta=item.meta)
    else:
        doc = engine.kb.add_document(db, title=title,
                                     text=raw.decode("utf-8", "replace"), source=source,
                                     modality="text", mime=mime)
    return {"id": doc.id, "title": doc.title, "modality": doc.modality}


@router.get("/documents", summary="List documents")
def list_documents(active: bool | None = None, db: Session = Depends(get_db)):
    q = db.query(Document)
    if active is not None:
        q = q.filter(Document.active == active)
    docs = q.order_by(Document.id.desc()).limit(500).all()
    return [{"id": d.id, "title": d.title, "source": d.source, "modality": d.modality,
             "active": d.active, "chars": len(d.content_text),
             "created_at": d.created_at.isoformat()} for d in docs]


@router.get("/documents/{doc_id}", summary="Get a document")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "not found")
    return {"id": d.id, "title": d.title, "source": d.source, "modality": d.modality,
            "mime": d.mime, "active": d.active, "meta": d.meta,
            "text": d.content_text, "created_at": d.created_at.isoformat()}


@router.delete("/documents/{doc_id}", summary="Deactivate a document (versioned, reversible)")
def deactivate_document(doc_id: int, db: Session = Depends(get_db),
                        engine: SynapseEngine = Depends(get_engine)):
    if not engine.kb.deactivate_document(db, doc_id):
        raise HTTPException(404, "not found")
    return {"id": doc_id, "active": False, "note": "deactivated; restore via KB rollback"}
