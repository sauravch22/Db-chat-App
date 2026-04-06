"""API routes for the Global Entity Knowledge Graph + Business Glossary."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from app.database import SessionLocal
from app.api.deps import get_current_user
from app.models import (
    EntityConcept, EntityMapping, ColumnFingerprint,
    GlossaryTerm, ColumnAnnotation, QueryCorrection,
    Connection,
)
from app.services.semantic_graph_service import SemanticGraphService

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge Graph"])


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Request / Response models ─────────────────────────────

class ConceptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    category: str = ""

class MappingCreate(BaseModel):
    concept_id: int
    connection_id: int
    table_name: str
    column_name: str
    confidence: int = 100
    source: str = "user"

class GlossaryCreate(BaseModel):
    term: str = Field(..., min_length=1, max_length=255)
    definition: str = Field(..., min_length=1)
    sql_expression: str = ""
    category: str = ""
    synonyms: str = ""

class AnnotationCreate(BaseModel):
    connection_id: int
    table_name: str
    column_name: str
    annotation: str = Field(..., min_length=1)

class CorrectionCreate(BaseModel):
    connection_id: int
    original_prompt: str
    original_sql: str = ""
    correction_text: str = Field(..., min_length=1)
    corrected_sql: str = ""
    correction_type: str = ""


# ── Entity Concepts ──────────────────────────────────────

@router.get("/concepts")
async def list_concepts(
    category: str = None,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    svc = SemanticGraphService(db)
    concepts = svc.list_concepts(category)
    return [
        {
            "id": c.id, "name": c.name, "description": c.description,
            "category": c.category, "created_at": str(c.created_at),
            "mapping_count": len(c.mappings),
        }
        for c in concepts
    ]


@router.post("/concepts")
async def create_concept(
    req: ConceptCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    svc = SemanticGraphService(db)
    existing = db.query(EntityConcept).filter(EntityConcept.name == req.name).first()
    if existing:
        raise HTTPException(400, f"Concept '{req.name}' already exists")
    c = svc.create_concept(req.name, req.description, req.category, int(user["sub"]))
    return {"id": c.id, "name": c.name, "status": "created"}


@router.get("/concepts/{concept_id}")
async def get_concept(
    concept_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    concept = db.query(EntityConcept).get(concept_id)
    if not concept:
        raise HTTPException(404, "Concept not found")
    svc = SemanticGraphService(db)
    mappings = svc.get_concept_mappings(concept_id)
    return {
        "id": concept.id, "name": concept.name,
        "description": concept.description, "category": concept.category,
        "mappings": [
            {
                "id": m.id, "connection_id": m.connection_id,
                "table_name": m.table_name, "column_name": m.column_name,
                "confidence": m.confidence, "source": m.source,
            }
            for m in mappings
        ],
    }


@router.delete("/concepts/{concept_id}")
async def delete_concept(
    concept_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    svc = SemanticGraphService(db)
    if not svc.delete_concept(concept_id):
        raise HTTPException(404, "Concept not found")
    return {"status": "deleted"}


# ── Entity Mappings ──────────────────────────────────────

@router.post("/mappings")
async def create_mapping(
    req: MappingCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    svc = SemanticGraphService(db)
    m = svc.add_mapping(
        req.concept_id, req.connection_id,
        req.table_name, req.column_name,
        req.confidence, req.source, int(user["sub"]),
    )
    return {"id": m.id, "status": "created"}


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    svc = SemanticGraphService(db)
    if not svc.delete_mapping(mapping_id):
        raise HTTPException(404, "Mapping not found")
    return {"status": "deleted"}


# ── Fingerprinting & Discovery ───────────────────────────

@router.post("/fingerprint/{connection_id}")
async def fingerprint_connection(
    connection_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    conn = db.query(Connection).filter(
        Connection.id == connection_id, Connection.is_active.is_(True),
    ).first()
    if not conn:
        raise HTTPException(404, "Connection not found")

    svc = SemanticGraphService(db)
    count = svc.fingerprint_connection(conn)
    return {"status": "ok", "columns_fingerprinted": count}


@router.get("/fingerprints/{connection_id}")
async def get_fingerprints(
    connection_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    fps = (
        db.query(ColumnFingerprint)
        .filter(ColumnFingerprint.connection_id == connection_id)
        .order_by(ColumnFingerprint.table_name, ColumnFingerprint.column_name)
        .all()
    )
    return [
        {
            "id": fp.id, "table": fp.table_name, "column": fp.column_name,
            "type": fp.data_type, "cardinality": fp.cardinality,
            "null_ratio": fp.null_ratio, "pattern": fp.pattern_class,
            "fingerprint": fp.fingerprint_hash,
            "samples": fp.sample_values,
        }
        for fp in fps
    ]


@router.get("/discover")
async def discover_matches(
    min_confidence: int = 70,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    svc = SemanticGraphService(db)
    return svc.discover_entity_matches(min_confidence)


@router.post("/discover/accept")
async def accept_discovery(
    req: MappingCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    """Accept an auto-discovered match by creating a mapping."""
    svc = SemanticGraphService(db)
    m = svc.add_mapping(
        req.concept_id, req.connection_id,
        req.table_name, req.column_name,
        req.confidence, "auto_fingerprint", int(user["sub"]),
    )
    return {"id": m.id, "status": "accepted"}


# ── Business Glossary ────────────────────────────────────

@router.get("/glossary")
async def list_glossary(
    category: str = None,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    q = db.query(GlossaryTerm).order_by(GlossaryTerm.term)
    if category:
        q = q.filter(GlossaryTerm.category == category)
    terms = q.all()
    return [
        {
            "id": t.id, "term": t.term, "definition": t.definition,
            "sql_expression": t.sql_expression, "category": t.category,
            "synonyms": t.synonyms, "upvotes": t.upvotes,
            "created_at": str(t.created_at),
        }
        for t in terms
    ]


@router.post("/glossary")
async def create_glossary_term(
    req: GlossaryCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    existing = db.query(GlossaryTerm).filter(GlossaryTerm.term == req.term).first()
    if existing:
        raise HTTPException(400, f"Term '{req.term}' already exists")
    t = GlossaryTerm(
        term=req.term, definition=req.definition,
        sql_expression=req.sql_expression or None,
        category=req.category or None,
        synonyms=req.synonyms or None,
        created_by=int(user["sub"]),
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id, "term": t.term, "status": "created"}


@router.put("/glossary/{term_id}")
async def update_glossary_term(
    term_id: int,
    req: GlossaryCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    t = db.query(GlossaryTerm).get(term_id)
    if not t:
        raise HTTPException(404, "Term not found")
    t.term = req.term
    t.definition = req.definition
    t.sql_expression = req.sql_expression or None
    t.category = req.category or None
    t.synonyms = req.synonyms or None
    t.updated_at = datetime.utcnow()
    db.commit()
    return {"id": t.id, "status": "updated"}


@router.post("/glossary/{term_id}/upvote")
async def upvote_glossary_term(
    term_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    t = db.query(GlossaryTerm).get(term_id)
    if not t:
        raise HTTPException(404, "Term not found")
    t.upvotes = (t.upvotes or 0) + 1
    db.commit()
    return {"upvotes": t.upvotes}


@router.delete("/glossary/{term_id}")
async def delete_glossary_term(
    term_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    t = db.query(GlossaryTerm).get(term_id)
    if not t:
        raise HTTPException(404, "Term not found")
    db.delete(t)
    db.commit()
    return {"status": "deleted"}


# ── Column Annotations ───────────────────────────────────

@router.get("/annotations/{connection_id}")
async def list_annotations(
    connection_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    anns = (
        db.query(ColumnAnnotation)
        .filter(ColumnAnnotation.connection_id == connection_id)
        .order_by(ColumnAnnotation.table_name, ColumnAnnotation.column_name)
        .all()
    )
    return [
        {
            "id": a.id, "table": a.table_name, "column": a.column_name,
            "annotation": a.annotation, "upvotes": a.upvotes,
            "created_at": str(a.created_at),
        }
        for a in anns
    ]


@router.post("/annotations")
async def create_annotation(
    req: AnnotationCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    a = ColumnAnnotation(
        connection_id=req.connection_id,
        table_name=req.table_name,
        column_name=req.column_name,
        annotation=req.annotation,
        annotated_by=int(user["sub"]),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "status": "created"}


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(
    annotation_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    a = db.query(ColumnAnnotation).get(annotation_id)
    if not a:
        raise HTTPException(404, "Annotation not found")
    db.delete(a)
    db.commit()
    return {"status": "deleted"}


# ── Query Corrections ────────────────────────────────────

@router.post("/corrections")
async def create_correction(
    req: CorrectionCreate,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    c = QueryCorrection(
        user_id=int(user["sub"]),
        connection_id=req.connection_id,
        original_prompt=req.original_prompt,
        original_sql=req.original_sql or None,
        correction_text=req.correction_text,
        corrected_sql=req.corrected_sql or None,
        correction_type=req.correction_type or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "status": "created"}


@router.get("/corrections/{connection_id}")
async def list_corrections(
    connection_id: int,
    limit: int = 50,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    corrections = (
        db.query(QueryCorrection)
        .filter(QueryCorrection.connection_id == connection_id)
        .order_by(QueryCorrection.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        {
            "id": c.id, "original_prompt": c.original_prompt,
            "original_sql": c.original_sql,
            "correction_text": c.correction_text,
            "corrected_sql": c.corrected_sql,
            "correction_type": c.correction_type,
            "applied_count": c.applied_count,
            "created_at": str(c.created_at),
        }
        for c in corrections
    ]


# ── Unified context endpoint ─────────────────────────────

@router.get("/context/{connection_id}")
async def get_knowledge_context(
    connection_id: int,
    db=Depends(_get_db),
    user=Depends(get_current_user),
):
    """Returns the full semantic context block that gets injected into LLM prompts."""
    svc = SemanticGraphService(db)
    entity_ctx = svc.build_entity_context(connection_id)
    glossary_ctx = svc.build_glossary_context(connection_id)
    return {
        "entity_context": entity_ctx,
        "glossary_context": glossary_ctx,
        "combined_length": len(entity_ctx) + len(glossary_ctx),
    }
