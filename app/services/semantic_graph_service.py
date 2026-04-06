"""Semantic Graph Service — cross-database entity resolution and fingerprinting.

Builds a living knowledge graph that maps physical columns to canonical
business concepts. Uses statistical fingerprinting to auto-detect columns
that likely represent the same real-world entity across databases.
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any

from sqlalchemy import text, inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models import (
    EntityConcept, EntityMapping, ColumnFingerprint,
    GlossaryTerm, ColumnAnnotation, QueryCorrection,
    Connection,
)
from app.services.chat_service import _get_engine

logger = logging.getLogger(__name__)

# Value-pattern classifiers (order matters — first match wins)
_PATTERN_RULES = [
    ("email",       re.compile(r'^[^@\s]+@[^@\s]+\.\w+$')),
    ("url",         re.compile(r'^https?://', re.I)),
    ("uuid",        re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)),
    ("phone",       re.compile(r'^\+?\d[\d\s\-().]{6,}$')),
    ("ip_address",  re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')),
    ("date_iso",    re.compile(r'^\d{4}-\d{2}-\d{2}')),
    ("currency",    re.compile(r'^[\$€£¥]\s?\d')),
    ("percentage",  re.compile(r'^\d+\.?\d*\s?%$')),
    ("boolean",     re.compile(r'^(true|false|yes|no|0|1|t|f|y|n)$', re.I)),
]


def _classify_pattern(samples: list) -> Optional[str]:
    """Classify a column's value pattern from sample data."""
    if not samples:
        return None
    non_null = [str(s) for s in samples if s is not None and str(s).strip()]
    if not non_null:
        return None
    for label, regex in _PATTERN_RULES:
        hits = sum(1 for v in non_null if regex.match(v))
        if hits / len(non_null) >= 0.6:
            return label
    if all(v.isdigit() for v in non_null):
        return "integer_id" if len(set(non_null)) == len(non_null) else "integer"
    return None


def _compute_fingerprint_hash(
    data_type: str, cardinality: int, null_ratio: int,
    pattern_class: Optional[str], avg_length: int,
) -> str:
    """Deterministic hash capturing the statistical shape of a column."""
    payload = f"{data_type}|{cardinality}|{null_ratio}|{pattern_class or ''}|{avg_length}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class SemanticGraphService:
    """Manages the global entity knowledge graph."""

    def __init__(self, db: Session):
        self.db = db

    # ── Fingerprinting ────────────────────────────────────

    def fingerprint_connection(self, connection: Connection, sample_limit: int = 200) -> int:
        """Compute fingerprints for every column in a connection. Returns count."""
        try:
            engine = _get_engine(connection, timeout=30)
        except Exception as e:
            logger.error("Cannot fingerprint conn=%d: %s", connection.id, e)
            return 0

        insp = sa_inspect(engine)
        count = 0

        for table_name in insp.get_table_names():
            if table_name.startswith("pg_") or table_name.startswith("sql_"):
                continue
            try:
                columns = insp.get_columns(table_name)
            except Exception:
                continue

            for col_info in columns:
                col_name = col_info["name"]
                col_type = str(col_info.get("type", "unknown")).split("(")[0].upper()

                try:
                    with engine.connect() as conn:
                        stats = conn.execute(text(
                            f'SELECT COUNT(*) AS total, '
                            f'COUNT(DISTINCT "{col_name}") AS distinct_cnt, '
                            f'SUM(CASE WHEN "{col_name}" IS NULL THEN 1 ELSE 0 END) AS nulls '
                            f'FROM "{table_name}"'
                        )).mappings().first()

                        total = int(stats["total"] or 0)
                        distinct_cnt = int(stats["distinct_cnt"] or 0)
                        null_cnt = int(stats["nulls"] or 0)
                        null_ratio = int((null_cnt / total * 100)) if total > 0 else 0

                        samples_r = conn.execute(text(
                            f'SELECT DISTINCT "{col_name}" FROM "{table_name}" '
                            f'WHERE "{col_name}" IS NOT NULL LIMIT {sample_limit}'
                        )).fetchall()
                        raw_samples = [row[0] for row in samples_r]

                        str_samples = [str(s) for s in raw_samples[:20] if s is not None]
                        avg_len = (
                            int(sum(len(s) for s in str_samples) / len(str_samples))
                            if str_samples else 0
                        )

                        min_val = str(raw_samples[0])[:200] if raw_samples else None
                        max_val = str(raw_samples[-1])[:200] if raw_samples else None

                except Exception as e:
                    logger.debug("Fingerprint stats failed for %s.%s: %s",
                                 table_name, col_name, e)
                    total = distinct_cnt = null_ratio = avg_len = 0
                    raw_samples = []
                    min_val = max_val = None

                pattern = _classify_pattern(raw_samples[:50])

                fp_hash = _compute_fingerprint_hash(
                    col_type, distinct_cnt, null_ratio, pattern, avg_len,
                )

                existing = self.db.query(ColumnFingerprint).filter(
                    ColumnFingerprint.connection_id == connection.id,
                    ColumnFingerprint.table_name == table_name,
                    ColumnFingerprint.column_name == col_name,
                ).first()

                if existing:
                    existing.data_type = col_type
                    existing.cardinality = distinct_cnt
                    existing.null_ratio = null_ratio
                    existing.min_value = min_val
                    existing.max_value = max_val
                    existing.avg_length = avg_len
                    existing.sample_values = json.dumps(str_samples[:10], default=str)
                    existing.pattern_class = pattern
                    existing.fingerprint_hash = fp_hash
                    existing.computed_at = datetime.utcnow()
                else:
                    self.db.add(ColumnFingerprint(
                        connection_id=connection.id,
                        table_name=table_name,
                        column_name=col_name,
                        data_type=col_type,
                        cardinality=distinct_cnt,
                        null_ratio=null_ratio,
                        min_value=min_val,
                        max_value=max_val,
                        avg_length=avg_len,
                        sample_values=json.dumps(str_samples[:10], default=str),
                        pattern_class=pattern,
                        fingerprint_hash=fp_hash,
                        computed_at=datetime.utcnow(),
                    ))
                count += 1

        self.db.commit()
        logger.info("Fingerprinted %d columns for connection %d", count, connection.id)
        return count

    # ── Auto-discovery ────────────────────────────────────

    def discover_entity_matches(self, min_confidence: int = 70) -> List[Dict[str, Any]]:
        """Find columns across connections that likely represent the same entity.

        Compares fingerprints by hash + name similarity. Returns proposed matches.
        """
        fps = self.db.query(ColumnFingerprint).all()
        if not fps:
            return []

        by_hash: Dict[str, List[ColumnFingerprint]] = {}
        for fp in fps:
            if fp.fingerprint_hash:
                by_hash.setdefault(fp.fingerprint_hash, []).append(fp)

        proposals: List[Dict[str, Any]] = []

        for fp_hash, group in by_hash.items():
            if len(group) < 2:
                continue
            cross_conn = {}
            for fp in group:
                cross_conn.setdefault(fp.connection_id, []).append(fp)
            if len(cross_conn) < 2:
                continue

            all_fps = list(group)
            for i, a in enumerate(all_fps):
                for b in all_fps[i + 1:]:
                    if a.connection_id == b.connection_id:
                        continue

                    confidence = 50
                    a_name = a.column_name.lower().replace("_", "").replace("-", "")
                    b_name = b.column_name.lower().replace("_", "").replace("-", "")
                    if a_name == b_name:
                        confidence += 30
                    elif a_name in b_name or b_name in a_name:
                        confidence += 15

                    if a.pattern_class and a.pattern_class == b.pattern_class:
                        confidence += 10
                    if a.data_type == b.data_type:
                        confidence += 5

                    try:
                        a_samples = set(json.loads(a.sample_values or "[]"))
                        b_samples = set(json.loads(b.sample_values or "[]"))
                        if a_samples and b_samples:
                            overlap = len(a_samples & b_samples) / max(len(a_samples | b_samples), 1)
                            confidence += int(overlap * 20)
                    except Exception:
                        pass

                    confidence = min(confidence, 100)
                    if confidence < min_confidence:
                        continue

                    proposals.append({
                        "column_a": {
                            "connection_id": a.connection_id,
                            "table": a.table_name,
                            "column": a.column_name,
                            "type": a.data_type,
                            "pattern": a.pattern_class,
                        },
                        "column_b": {
                            "connection_id": b.connection_id,
                            "table": b.table_name,
                            "column": b.column_name,
                            "type": b.data_type,
                            "pattern": b.pattern_class,
                        },
                        "confidence": confidence,
                        "fingerprint_hash": fp_hash,
                    })

        proposals.sort(key=lambda p: p["confidence"], reverse=True)
        return proposals

    # ── Entity CRUD ───────────────────────────────────────

    def create_concept(self, name: str, description: str = "",
                       category: str = "", user_id: int = None) -> EntityConcept:
        concept = EntityConcept(
            name=name, description=description,
            category=category, created_by=user_id,
        )
        self.db.add(concept)
        self.db.commit()
        self.db.refresh(concept)
        return concept

    def list_concepts(self, category: str = None) -> List[EntityConcept]:
        q = self.db.query(EntityConcept)
        if category:
            q = q.filter(EntityConcept.category == category)
        return q.order_by(EntityConcept.name).all()

    def add_mapping(self, concept_id: int, connection_id: int,
                    table_name: str, column_name: str,
                    confidence: int = 100, source: str = "user",
                    user_id: int = None) -> EntityMapping:
        mapping = EntityMapping(
            concept_id=concept_id, connection_id=connection_id,
            table_name=table_name, column_name=column_name,
            confidence=confidence, source=source,
            verified_by=user_id,
            verified_at=datetime.utcnow() if user_id else None,
        )
        self.db.add(mapping)
        self.db.commit()
        self.db.refresh(mapping)
        return mapping

    def get_concept_mappings(self, concept_id: int) -> List[EntityMapping]:
        return (
            self.db.query(EntityMapping)
            .filter(EntityMapping.concept_id == concept_id)
            .all()
        )

    def delete_concept(self, concept_id: int) -> bool:
        c = self.db.query(EntityConcept).get(concept_id)
        if not c:
            return False
        self.db.delete(c)
        self.db.commit()
        return True

    def delete_mapping(self, mapping_id: int) -> bool:
        m = self.db.query(EntityMapping).get(mapping_id)
        if not m:
            return False
        self.db.delete(m)
        self.db.commit()
        return True

    # ── Context builder for LLM ───────────────────────────

    def build_entity_context(self, connection_id: int) -> str:
        """Build a text block the LLM can use to understand cross-DB entities."""
        mappings = (
            self.db.query(EntityMapping)
            .filter(EntityMapping.connection_id == connection_id)
            .all()
        )
        if not mappings:
            return ""

        concept_ids = {m.concept_id for m in mappings}
        concepts = (
            self.db.query(EntityConcept)
            .filter(EntityConcept.id.in_(concept_ids))
            .all()
        )
        concept_map = {c.id: c for c in concepts}

        lines = ["ENTITY MAPPINGS (columns linked to business concepts):"]
        for m in mappings:
            c = concept_map.get(m.concept_id)
            if not c:
                continue
            lines.append(
                f"  {m.table_name}.{m.column_name} → concept '{c.name}'"
                f"{' (' + c.description + ')' if c.description else ''}"
            )

        all_mappings = (
            self.db.query(EntityMapping)
            .filter(
                EntityMapping.concept_id.in_(concept_ids),
                EntityMapping.connection_id != connection_id,
            )
            .all()
        )
        if all_mappings:
            lines.append("\nCROSS-DATABASE LINKS (same concepts in other databases):")
            for m in all_mappings:
                c = concept_map.get(m.concept_id)
                if c:
                    lines.append(
                        f"  conn={m.connection_id} {m.table_name}.{m.column_name}"
                        f" → '{c.name}' (confidence={m.confidence}%)"
                    )

        return "\n".join(lines)

    # ── Glossary context for LLM ──────────────────────────

    def build_glossary_context(self, connection_id: int = None) -> str:
        """Build glossary + annotation text the LLM uses for SQL generation."""
        parts = []

        terms = self.db.query(GlossaryTerm).order_by(GlossaryTerm.term).all()
        if terms:
            parts.append("BUSINESS GLOSSARY (use these definitions when mentioned):")
            for t in terms:
                line = f"  '{t.term}': {t.definition}"
                if t.sql_expression:
                    line += f"  [SQL: {t.sql_expression}]"
                if t.synonyms:
                    line += f"  (also known as: {t.synonyms})"
                parts.append(line)

        if connection_id:
            annotations = (
                self.db.query(ColumnAnnotation)
                .filter(ColumnAnnotation.connection_id == connection_id)
                .order_by(ColumnAnnotation.table_name, ColumnAnnotation.column_name)
                .all()
            )
            if annotations:
                parts.append("\nCOLUMN ANNOTATIONS (user-provided descriptions):")
                for a in annotations:
                    parts.append(
                        f"  {a.table_name}.{a.column_name}: {a.annotation}"
                    )

        return "\n".join(parts)

    # ── Corrections context ───────────────────────────────

    def build_corrections_context(self, connection_id: int, prompt: str) -> str:
        """Find relevant past corrections using Jaccard word-similarity scoring."""
        corrections = (
            self.db.query(QueryCorrection)
            .filter(QueryCorrection.connection_id == connection_id)
            .order_by(QueryCorrection.applied_count.desc())
            .limit(30)
            .all()
        )
        if not corrections:
            return ""

        prompt_words = set(prompt.lower().split())
        if not prompt_words:
            return ""

        scored: list[tuple[float, QueryCorrection]] = []
        for c in corrections:
            corr_words = set(c.original_prompt.lower().split())
            if not corr_words:
                continue
            jaccard = len(prompt_words & corr_words) / len(prompt_words | corr_words)
            if jaccard >= 0.15:
                scored.append((jaccard, c))

        if not scored:
            return ""

        scored.sort(key=lambda x: x[0], reverse=True)
        relevant = [c for _, c in scored[:5]]

        lines = ["PAST CORRECTIONS (learn from these):\n"]
        for c in relevant:
            lines.append(f"  User asked: {c.original_prompt}")
            if c.original_sql:
                lines.append(f"  Wrong SQL: {c.original_sql}")
            lines.append(f"  Correction: {c.correction_text}")
            if c.corrected_sql:
                lines.append(f"  Correct SQL: {c.corrected_sql}")
            lines.append("")

        return "\n".join(lines)
