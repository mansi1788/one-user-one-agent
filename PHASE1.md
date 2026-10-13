# Phase 1
Local-only ingestion, SQLite memory, evidence resolution and eligibility. No model calls or actions.

Run from the workspace with Python 3.11+:
```powershell
$env:PYTHONPATH = "src"
python -m one_agent.cli validate --pack .
python -m one_agent.cli ingest --pack . --db viewer_memory.sqlite3
python -m one_agent.cli viewer --db viewer_memory.sqlite3 --user U-00042 --as-of 2026-09-30T18:30:00Z
python -m pytest -q
```

The validate command opens only supplied files for reading. Ingest and viewer write only the explicitly selected local database. Triggers are staged without applying future settings to historical memory. All profile source rows are retained. Received timestamps govern event ordering; original device timestamps remain in each payload.

Eligibility is separate from goal commitment. G06/G10/G11 are explicitly disabled. G07 remains unknown where finite history cannot establish unwatched episodes. Lifetime absence is never inferred. Receipt-time windows require complete source coverage; buffered device chronology remains uncertain. Stale positive consent requires verification; a negative snapshot or observed opt-out blocks consent. No undocumented expiry transition is invented.

Goal/plan state and decision audit tables are available; automated goal selection, replay control application, outcome judgments, action publication and model providers are outside Phase 1. A single dataset per database is supported: source row references identify profile/trigger versions within that pack. Use a fresh database for a different pack. Imported files remain unchanged.
