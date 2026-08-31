import pytest
from pydantic import ValidationError

from ssa.config import Settings


def test_settings_reads_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@h/db"
    assert settings.extraction_model == "claude-haiku-4-5"


def test_settings_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
