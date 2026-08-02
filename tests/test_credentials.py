"""Keeping a build's S3 secret alive.

The behaviour that matters is when the secret gets re-issued, so the tests
drive the clock and record the statements rather than talking to DuckDB.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from credentials import DEFAULT_INTERVAL, DEFAULT_TTL, Secret  # noqa: E402


class FakeConn:
    """Records what was executed, as DuckDB would receive it."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, object]] = []

    def execute(self, query, parameters=None):
        self.statements.append((query, parameters))
        return self


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 2, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("QUERIA_S3_ENDPOINT_HOST", "example.r2.cloudflarestorage.com")
    monkeypatch.setenv("QUERIA_DATA_URL", "s3://bucket/queria/thing/")
    monkeypatch.delenv("QUERIA_S3_REGION", raising=False)
    monkeypatch.delenv("QUERIA_S3_USE_SSL", raising=False)


def test_install_creates_the_secret(env):
    conn = FakeConn()
    Secret(conn).install()
    query, params = conn.statements[0]
    assert "CREATE OR REPLACE SECRET queria_build" in query
    assert "CHAIN 'process'" in query
    assert params == ["example.r2.cloudflarestorage.com", "auto"]


def test_replaces_rather_than_accumulates(env):
    # An unnamed secret would leave a new one behind on every refresh.
    conn = FakeConn()
    secret = Secret(conn)
    secret.install()
    secret.refresh()
    assert all("CREATE OR REPLACE SECRET queria_build" in q for q, _ in conn.statements)
    assert len(conn.statements) == 2


def test_refresh_if_due_waits_for_the_interval(env):
    conn = FakeConn()
    clock = Clock()
    secret = Secret(conn, clock=clock)
    secret.install()

    # A tight loop must not mint on every pass -- the interval decides, not
    # the call site, so a seam every few seconds is fine to call from.
    for _ in range(100):
        clock.advance(timedelta(seconds=1))
        secret.refresh_if_due()
    assert len(conn.statements) == 1

    clock.advance(DEFAULT_INTERVAL)
    secret.refresh_if_due()
    assert len(conn.statements) == 2


def test_refresh_lands_before_the_credential_expires(env):
    # The point of the interval: the replacement has to arrive while the
    # credential it replaces is still good, even on the shortest TTL.
    assert DEFAULT_INTERVAL < DEFAULT_TTL


def test_use_ssl_is_a_literal_not_a_parameter(env, monkeypatch):
    # DuckDB takes USE_SSL as a literal in the option list. Passing it as a
    # parameter is a syntax error, so it has to be interpolated.
    monkeypatch.setenv("QUERIA_S3_USE_SSL", "false")
    conn = FakeConn()
    Secret(conn).install()
    query, params = conn.statements[0]
    assert "USE_SSL false" in query
    assert len(params) == 2


def test_region_can_be_overridden(env, monkeypatch):
    monkeypatch.setenv("QUERIA_S3_REGION", "apac")
    conn = FakeConn()
    Secret(conn).install()
    assert conn.statements[0][1][1] == "apac"


def test_needed_only_for_remote_storage(env, monkeypatch):
    assert Secret.needed() is True
    # A build against a local path has nothing to sign.
    monkeypatch.setenv("QUERIA_DATA_URL", "/tmp/thing.files/")
    assert Secret.needed() is False
    monkeypatch.delenv("QUERIA_DATA_URL")
    assert Secret.needed() is False
