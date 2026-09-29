from sqlalchemy import select

from ssa.connectors.ods import load_upper_limits
from ssa.models import Entity, UpperLimit


def test_load_upper_limits_creates_entities_and_limits(session):
    count = load_upper_limits(session, "data/upper_limits.csv")

    assert count >= 15
    limits = list(session.scalars(select(UpperLimit)).all())
    assert len(limits) == count

    b6 = session.scalars(select(Entity).where(Entity.canonical_name == "Vitamin B6")).one()
    b6_limit = session.scalars(select(UpperLimit).where(UpperLimit.entity_id == b6.id)).one()
    assert b6_limit.amount == 100.0
    assert b6_limit.unit == "mg"
    assert "neuropathy" in b6_limit.basis


def test_load_upper_limits_is_idempotent(session):
    first = load_upper_limits(session, "data/upper_limits.csv")
    second = load_upper_limits(session, "data/upper_limits.csv")

    assert second == 0
    assert len(list(session.scalars(select(UpperLimit)).all())) == first


def test_malformed_row_is_refused(session, tmp_path):
    import pytest

    path = tmp_path / "ul.csv"
    path.write_text(
        "canonical_name,amount,unit,population,basis,source_url\n"
        "Vitamin D3,100,mcg,adult,all forms, not D3 alone,https://ods.example/\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unquoted comma"):
        load_upper_limits(session, path)


def test_shipped_upper_limits_all_cite_a_url(session):
    from ssa.models import UpperLimit

    load_upper_limits(session, "data/upper_limits.csv")

    for row in session.query(UpperLimit).all():
        assert row.source_url.startswith("https://"), row.source_url
