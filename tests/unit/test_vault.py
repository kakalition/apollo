"""Vault: path sandboxing, frontmatter parsing, DB + FTS synchronisation."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from apollo.db import tables as t
from apollo.db.fts import search_vault
from apollo.tools.vault import Vault, VaultError


def test_path_sandbox_rejects_escape(settings) -> None:
    vault = Vault(settings.vault_path)
    with pytest.raises(VaultError):
        vault.read("../../etc/passwd")


def test_write_read_roundtrip(settings) -> None:
    vault = Vault(settings.vault_path)
    path = vault.write("notes/hello.md", "hello world")
    assert path == "notes/hello.md"
    assert vault.read("notes/hello.md") == "hello world"


def test_sync_indexes_and_searches(db, settings) -> None:
    vault = Vault(settings.vault_path)
    vault.write(
        "journal/2026-03-01.md",
        "---\ntitle: Morning pages\ntags: [journal, focus]\ndate: 2026-03-01\n---\n\n"
        "Worked on the rocket telemetry system today.",
    )
    with db.write() as session:
        stats = vault.sync(session)
    assert stats.added == 1

    with db.session() as session:
        entries = list(session.execute(select(t.JournalEntry)).scalars())
    assert len(entries) == 1
    assert entries[0].title == "Morning pages"
    assert entries[0].tags == ["journal", "focus"]

    with db.session() as session:
        hits = search_vault(session.connection(), "telemetry")
    assert hits and hits[0]["body_path"] == "journal/2026-03-01.md"


def test_sync_only_reindexes_on_change(db, settings) -> None:
    vault = Vault(settings.vault_path)
    vault.write("notes/a.md", "first version")
    with db.write() as session:
        assert vault.sync(session).added == 1
    with db.write() as session:
        assert vault.sync(session).changed == 0
    vault.write("notes/a.md", "second version")
    with db.write() as session:
        stats = vault.sync(session)
    assert stats.updated == 1


def test_sync_removes_deleted_files(db, settings) -> None:
    vault = Vault(settings.vault_path)
    vault.write("notes/gone.md", "temporary")
    with db.write() as session:
        vault.sync(session)
    vault.delete("notes/gone.md")
    with db.write() as session:
        stats = vault.sync(session)
    assert stats.removed == 1
    with db.session() as session:
        assert list(session.execute(select(t.JournalEntry)).scalars()) == []
