# Supplement Stack Analyzer

Supplement Stack Analyzer finds interactions, redundancies, upper-limit breaches, and timing conflicts across a person's supplements and prescriptions.

## Core rule

The LLM never decides whether an interaction exists. It extracts candidate triples from source documents offline, and every triple must carry a verbatim source span that is programmatically verified before storage. At analysis time, detection is a deterministic database lookup — no LLM in the request path.

## Setup

```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
alembic upgrade head
```

## Test

```
pytest -v
```
