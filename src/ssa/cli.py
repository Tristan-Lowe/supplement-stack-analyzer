"""Command-line entry points for seeding, ingesting, and analyzing."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from ssa.analyze.engine import analyze_stack
from ssa.bootstrap import enrich_drug_aliases
from ssa.config import Settings
from ssa.connectors.ods import load_nutrient_synonyms, load_upper_limits
from ssa.connectors.openfda import fetch_interaction_sections
from ssa.curated import load_supplement_registry, renormalize_aliases
from ssa.db import make_engine, make_session_factory
from ssa.extract.llm import make_client
from ssa.extract.schema import VALID_DIRECTIONS
from ssa.models import (
    Base,
    Entity,
    EntityAlias,
    EntityKind,
    EvidenceGrade,
    PipelineRun,
    Severity,
    utcnow,
)
from ssa.pipeline import content_key, ingest_section, replay_quarantine
from ssa.registry import find_nutrient_duplicates, merge_entities, reclassify_entities
from ssa.review import approve, list_pending, reject


def _session():
    return make_session_factory(make_engine())()


def cmd_init_db(args: argparse.Namespace) -> int:
    """Create the schema on the configured database.

    Without this a first-time user has no route from a fresh DATABASE_URL to a
    usable database, since Alembic migrations are not wired up yet.
    """
    engine = make_engine()
    Base.metadata.create_all(engine)
    print(f"Schema created on {engine.url.render_as_string(hide_password=True)}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    session = _session()
    try:
        repaired = renormalize_aliases(session)
        print(f"Re-normalized {repaired} stored alias key(s).")
        created = load_upper_limits(session, args.csv)
        print(f"Loaded {created} new upper limits.")
        aliases = load_nutrient_synonyms(session, args.synonyms)
        print(f"Loaded {aliases} new nutrient synonyms.")
        report = load_supplement_registry(session, args.registry)
        print(
            f"Curated registry: {report.created} new entities, "
            f"{report.aliases} new aliases, {len(report.merged)} merged."
        )
        for old, new in report.merged:
            print(f"  merged {old} -> {new}")
    finally:
        session.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest one drug's label sections under a tracked pipeline run.

    Every interaction edge is stamped with the run that produced it, which is what
    makes releases diffable.
    """
    settings = Settings()
    # One engine, one pool, reused for every section. Building an engine per call
    # would spin up a fresh connection pool each time for no benefit.
    engine = make_engine()
    session_factory = make_session_factory(engine)
    session = session_factory()
    client = make_client(settings)
    totals = {"extracted": 0, "stored": 0, "quarantined": 0}

    run = PipelineRun(source="openfda", stats={})
    session.add(run)
    session.commit()

    try:
        sections = fetch_interaction_sections(args.drug)
        if not sections:
            print(f"No label sections retrieved for {args.drug!r}.")
            run.finished_at = utcnow()
            run.stats = {"drug": args.drug, "sections": 0, **totals}
            session.commit()
            return 1

        # Deduplicate by content before paying for extraction. openFDA returns one
        # section per manufacturer label, and for generic drugs those carry the
        # same FDA-mandated wording — warfarin returns five sections that are
        # 97.8-100% identical. Extracting each would cost 5x for 1x of information.
        seen: set[str] = set()
        unique: list = []
        for section in sections:
            key = content_key(section.text)
            if key in seen:
                continue
            seen.add(key)
            unique.append(section)

        skipped = len(sections) - len(unique)
        if skipped:
            print(f"Skipped {skipped} duplicate label section(s) of {len(sections)}.")

        for section in unique:
            stats = ingest_section(
                session_factory,
                client,
                section.text,
                source="openfda",
                source_url=section.source_url,
                model=settings.extraction_model,
                pipeline_run_id=run.id,
            )
            for key in totals:
                totals[key] += stats[key]

        run.finished_at = utcnow()
        run.stats = {
            "drug": args.drug,
            "sections_fetched": len(sections),
            "sections_extracted": len(unique),
            **totals,
        }
        session.commit()
        run_id = run.id
    finally:
        session.close()

    print(
        f"{args.drug} (run {run_id}): {totals['extracted']} extracted, "
        f"{totals['stored']} stored, {totals['quarantined']} quarantined."
    )
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    """Add RxNorm brand names and salt forms to drugs that do not have them yet.

    Network I/O against RxNorm; ingestion-time only. Drugs already enriched are
    skipped unless --all is given, so re-running after an ingest is cheap.
    """
    session = _session()
    try:
        enriched = set(
            session.scalars(
                select(EntityAlias.entity_id).where(
                    EntityAlias.source.in_(("rxnorm_brand", "rxnorm_salt"))
                )
            ).all()
        )
        drugs = session.scalars(
            select(Entity).where(Entity.kind == EntityKind.DRUG, Entity.rxcui.is_not(None))
        ).all()
        total = 0
        for drug in drugs:
            if drug.id in enriched and not args.all:
                continue
            added = enrich_drug_aliases(session, drug)
            total += len(added)
            if added:
                print(f"  {drug.canonical_name}: {', '.join(added)}")
        print(f"Added {total} brand/salt alias(es).")
        return 0
    finally:
        session.close()


def cmd_replay(args: argparse.Namespace) -> int:
    """Retry quarantined triples against the current registry. Offline and free."""
    session = _session()
    try:
        stats = replay_quarantine(session)
        print(
            f"Examined {stats['examined']}: recovered {stats['recovered']}, "
            f"still unresolved {stats['still_unresolved']}, "
            f"self-pairs skipped {stats['self_pairs']}."
        )
        return 0
    finally:
        session.close()


def cmd_classes(args: argparse.Namespace) -> int:
    """Load curated drug classes and their RxClass memberships. Network; ingestion only."""
    from ssa.classes import load_drug_classes

    session = _session()
    try:
        report = load_drug_classes(session, args.csv)
        print(
            f"{report.classes} classes, {report.memberships} new memberships, "
            f"{report.new_drugs} new drug entities."
        )
        if report.failed_codes:
            print(f"RxClass lookups failed for: {', '.join(report.failed_codes)}")
        if report.skipped_ambiguous:
            print(f"Skipped ambiguous members: {', '.join(report.skipped_ambiguous)}")
        return 1 if report.failed_codes else 0
    finally:
        session.close()


def cmd_analyze(args: argparse.Namespace) -> int:
    session = _session()
    try:
        report = analyze_stack(session, args.stack)
    finally:
        session.close()

    print(report.summary)
    print()
    for finding in report.findings:
        print(f"[{finding.severity.value.upper()}] {finding.title}")
        print(f"  {finding.detail}")
        for citation in finding.citations:
            print(f"  source: {citation.source_url}")
        print()
    print(report.disclaimer)
    return 0


def cmd_dedupe(args: argparse.Namespace) -> int:
    """Fold bootstrap-created duplicates back into their seeded nutrient.

    Ingestion can meet a chemical name before the registry knows it is a synonym,
    and create a second entity for one substance. Only one of the pair carries the
    UpperLimit row, so the split silently disables a toxicity check.
    """
    session = _session()
    try:
        duplicates = find_nutrient_duplicates(session)
        if duplicates:
            print(f"{len(duplicates)} duplicate(s) found:")
            for dup_id, canon_id, name in duplicates:
                canonical = session.get(Entity, canon_id)
                print(f"  [{dup_id}] {name} -> [{canon_id}] {canonical.canonical_name}")
        else:
            print("No duplicates found.")

        if not args.apply:
            print()
            print("Dry run. Re-run with --apply to merge and reclassify.")
            return 0

        for dup_id, canon_id, name in duplicates:
            moved = merge_entities(session, dup_id, canon_id)
            print(f"  merged {name}: {moved}")
        if duplicates:
            print(f"Merged {len(duplicates)} duplicate(s).")

        changed = reclassify_entities(session)
        if changed:
            print(f"\nReclassified {len(changed)} entity kind(s):")
            for name, old_kind, new_kind in changed:
                print(f"  {name}: {old_kind} -> {new_kind}")
        return 0
    finally:
        session.close()


def cmd_review(args: argparse.Namespace) -> int:
    session = _session()
    try:
        if args.action == "list":
            items = list_pending(session)
            if not items:
                print("Nothing awaiting review.")
                return 0
            print(f"{len(items)} interaction(s) awaiting review:\n")
            for item in items:
                print(f"[{item.interaction_id}] {item.pair}")
                print(
                    f"    {item.severity.upper()} | evidence {item.evidence_grade} "
                    f"| confidence {item.confidence:.2f}"
                )
                print(f"    {item.mechanism}")
                for span in item.spans[:1]:
                    print(f'    quoted: "{span[:120]}"')
                for source in item.sources[:1]:
                    print(f"    source: {source}")
                print()
            print("Approve with:  ssa review approve <id>")
            print("Reject with:   ssa review reject <id>")
            return 0

        if args.action == "approve":
            result = approve(
                session,
                args.id,
                reviewer=args.reviewer,
                note=args.note,
                severity=Severity(args.severity) if args.severity else None,
                evidence_grade=EvidenceGrade(args.evidence) if args.evidence else None,
                direction=args.direction,
                affected_entity_id=args.affected,
            )
        else:
            result = reject(session, args.id, reviewer=args.reviewer, note=args.note)
        if result is None:
            print(f"No interaction with id {args.id}.")
            return 1
        print(f"Interaction {args.id} -> {result.status.value}")
        return 0
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(prog="ssa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Create the schema on DATABASE_URL")
    init_db.set_defaults(func=cmd_init_db)

    seed = subparsers.add_parser("seed", help="Load upper intake limits from CSV")
    seed.add_argument("--csv", default="data/upper_limits.csv")
    seed.add_argument("--synonyms", default="data/nutrient_synonyms.csv")
    seed.add_argument("--registry", default="data/supplement_registry.csv")
    seed.set_defaults(func=cmd_seed)

    enrich = subparsers.add_parser("enrich", help="Add RxNorm brand names and salt forms")
    enrich.add_argument("--all", action="store_true", help="re-check already-enriched drugs")
    enrich.set_defaults(func=cmd_enrich)

    classes = subparsers.add_parser("classes", help="Load drug classes from RxClass")
    classes.add_argument("--csv", default="data/drug_classes.csv")
    classes.set_defaults(func=cmd_classes)

    replay = subparsers.add_parser("replay", help="Retry quarantined triples (offline)")
    replay.set_defaults(func=cmd_replay)

    ingest = subparsers.add_parser("ingest", help="Ingest openFDA label sections for a drug")
    ingest.add_argument("drug")
    ingest.set_defaults(func=cmd_ingest)

    dedupe = subparsers.add_parser("dedupe", help="Merge duplicate entities into seeded nutrients")
    dedupe.add_argument("--apply", action="store_true", help="actually merge (default: dry run)")
    dedupe.set_defaults(func=cmd_dedupe)

    review = subparsers.add_parser("review", help="Review interactions held for approval")
    review.add_argument("action", choices=["list", "approve", "reject"])
    review.add_argument("id", nargs="?", type=int, help="interaction id (approve/reject)")
    review.add_argument("--reviewer", default="unspecified", help="who is deciding")
    review.add_argument("--note", help="why; stored with the decision")
    review.add_argument("--severity", choices=[s.value for s in Severity])
    review.add_argument("--evidence", choices=[g.value for g in EvidenceGrade])
    review.add_argument("--direction", choices=sorted(VALID_DIRECTIONS))
    review.add_argument("--affected", type=int, help="entity id the direction acts on")
    review.set_defaults(func=cmd_review)

    analyze = subparsers.add_parser("analyze", help="Analyze a stack given as text")
    analyze.add_argument("stack")
    analyze.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
