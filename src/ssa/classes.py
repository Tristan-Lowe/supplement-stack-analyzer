"""Drug classes: curated class names, members from RxClass.

Label warnings are often written about classes — "NSAIDs may increase bleeding
risk", "separate from antacids". Before this module those sentences quarantined,
because a class is not one drug, and binding "NSAIDs" to ibuprofen alone would
narrow a warning to one member. Classes are now entities of their own, and
membership comes only from RxClass (NLM's ATC classification), never from a model.

**Ingestion only.** `load_drug_classes` makes network calls.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ssa.connectors.rxclass import ClassMember, class_members, class_url
from ssa.models import ClassMembership, Entity, EntityKind
from ssa.registry import add_alias, classes_of, find_by_alias, get_or_create_entity  # noqa: F401

DRUG_CLASSES_CSV = "data/drug_classes.csv"

logger = logging.getLogger(__name__)


@dataclass
class ClassLoadReport:
    classes: int = 0
    memberships: int = 0
    new_drugs: int = 0
    failed_codes: list[str] = field(default_factory=list)
    skipped_ambiguous: list[str] = field(default_factory=list)


def _member_entity(session: Session, member: ClassMember, report: ClassLoadReport) -> Entity | None:
    """The registry entity for a class member, created from RxClass data if absent."""
    by_rxcui = session.scalars(
        select(Entity).where(Entity.rxcui == member.rxcui, Entity.kind != EntityKind.CLASS)
    ).all()
    if len(by_rxcui) == 1:
        return by_rxcui[0]

    by_name = [e for e in find_by_alias(session, member.name) if e.kind is not EntityKind.CLASS]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        report.skipped_ambiguous.append(member.name)
        return None

    from ssa.bootstrap import _title_case, classify_kind  # local: bootstrap imports registry

    name = _title_case(member.name)
    entity = get_or_create_entity(session, classify_kind(name), name, rxcui=member.rxcui)
    add_alias(session, entity, member.name, source="rxclass")
    report.new_drugs += 1
    return entity


def load_drug_classes(
    session: Session,
    csv_path: str | Path = DRUG_CLASSES_CSV,
    fetch: Callable[[str], list[ClassMember] | None] = class_members,
) -> ClassLoadReport:
    """Create class entities with aliases, and their RxClass memberships. Idempotent.

    A class whose RxClass lookup fails keeps its existing members; nothing is
    removed on a failed fetch.
    """
    report = ClassLoadReport()
    rows = csv.DictReader(Path(csv_path).read_text(encoding="utf-8").splitlines())

    for row in rows:
        cls = get_or_create_entity(session, EntityKind.CLASS, row["canonical_name"])
        for alias in (row.get("aliases") or "").split("|"):
            if alias.strip():
                add_alias(session, cls, alias.strip(), source="curated_class")
        report.classes += 1

        existing = set(
            session.scalars(
                select(ClassMembership.member_id).where(ClassMembership.class_id == cls.id)
            ).all()
        )
        for code in row["atc_codes"].split("|"):
            code = code.strip()
            members = fetch(code)
            if members is None:
                report.failed_codes.append(code)
                continue
            for member in members:
                entity = _member_entity(session, member, report)
                if entity is None or entity.id in existing or entity.id == cls.id:
                    continue
                session.add(
                    ClassMembership(
                        class_id=cls.id,
                        member_id=entity.id,
                        source=f"rxclass:ATC:{code}",
                        source_url=class_url(code),
                    )
                )
                existing.add(entity.id)
                report.memberships += 1
        session.commit()

    return report
