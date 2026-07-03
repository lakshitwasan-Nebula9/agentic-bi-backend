"""Connector-wide sync (POST /connectors/{id}/sync): fans out to datasets, loads rows,
writes sync logs, and preserves the first-sync → KPI-generation guard.

Uses a self-connector pointing at the app DB (same pattern as test_datasets) and
pre-seeds a KPI per dataset so auto-generation is deterministically skipped — the
"triggers on first sync" path is identical to the datasets router (see test_datasets).

Follows the CLAUDE.md test contract: unique identifiers per test, cleaned up in teardown.
"""

import uuid
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.connector import DataConnector
from app.models.dataset import Dataset, DatasetRecord
from app.models.kpi import KPIDefinition
from app.models.schema_metadata import SchemaMetadata
from app.models.sync_log import SyncLog
from app.models.user import User

client = TestClient(app)

_emails: list[str] = []
_connector_ids: list[uuid.UUID] = []
_dataset_ids: list[uuid.UUID] = []
_tables: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        if _dataset_ids:
            db.query(KPIDefinition).filter(KPIDefinition.dataset_id.in_(_dataset_ids)).delete(
                synchronize_session=False
            )
            db.query(DatasetRecord).filter(DatasetRecord.dataset_id.in_(_dataset_ids)).delete(
                synchronize_session=False
            )
            db.query(SchemaMetadata).filter(SchemaMetadata.dataset_id.in_(_dataset_ids)).delete(
                synchronize_session=False
            )
            db.query(Dataset).filter(Dataset.id.in_(_dataset_ids)).delete(synchronize_session=False)
        if _connector_ids:
            db.query(SyncLog).filter(SyncLog.connector_id.in_(_connector_ids)).delete(
                synchronize_session=False
            )
            db.query(DataConnector).filter(DataConnector.id.in_(_connector_ids)).delete(
                synchronize_session=False
            )
        if _emails:
            db.query(User).filter(User.email.in_(_emails)).delete(synchronize_session=False)
        for tbl in _tables:
            db.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
        db.commit()
    finally:
        db.close()
        for bucket in (_emails, _connector_ids, _dataset_ids, _tables):
            bucket.clear()


def _headers() -> dict[str, str]:
    email = f"connsync-{uuid.uuid4().hex}@example.com"
    _emails.append(email)
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _self_connector(headers: dict[str, str]) -> str:
    parsed = urlparse(settings.DATABASE_URL)
    resp = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={
            "name": f"self-{uuid.uuid4().hex}",
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "database_name": parsed.path.lstrip("/"),
            "username": parsed.username,
            "password": parsed.password,
        },
    )
    assert resp.status_code == 201
    cid = resp.json()["id"]
    _connector_ids.append(uuid.UUID(cid))
    return cid


def test_sync_missing_connector_returns_404():
    resp = client.post(f"/api/v1/connectors/{uuid.uuid4()}/sync", headers=_headers())
    assert resp.status_code == 404


def test_sync_connector_with_no_datasets_is_empty():
    headers = _headers()
    cid = _self_connector(headers)
    resp = client.post(f"/api/v1/connectors/{cid}/sync", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["datasets_total"] == 0
    assert body["datasets_synced"] == 0
    assert body["total_rows"] == 0
    assert body["kpi_generation_triggered"] == 0


def test_sync_connector_loads_all_datasets_and_writes_logs():
    headers = _headers()
    cid = _self_connector(headers)

    table = f"connsync_{uuid.uuid4().hex}"
    _tables.append(table)
    db = SessionLocal()
    try:
        db.execute(text(f"CREATE TABLE {table} (id INT, region TEXT, amount NUMERIC)"))
        db.execute(
            text(f"INSERT INTO {table} VALUES (1,'north',100),(2,'south',200),(3,'east',300)")
        )
        db.commit()
    finally:
        db.close()

    # Two datasets; pre-seed a KPI on each so first-sync auto-generation is skipped.
    for i in range(2):
        ds = client.post(
            "/api/v1/datasets",
            headers=headers,
            json={
                "name": f"ds-{i}-{uuid.uuid4().hex}",
                "connector_id": cid,
                "source_query": f"SELECT * FROM {table}",
            },
        )
        assert ds.status_code == 201
        ds_id = ds.json()["id"]
        _dataset_ids.append(uuid.UUID(ds_id))
        db = SessionLocal()
        try:
            db.add(
                KPIDefinition(
                    dataset_id=uuid.UUID(ds_id),
                    table_name=table,
                    name=f"seeded-{uuid.uuid4().hex}",
                    display_name="Seeded",
                    description="skip auto-gen",
                    category="operational",
                    formula="SUM(amount)",
                    sql_expression="SUM(amount)",
                    direction="up_is_good",
                    status="draft",
                )
            )
            db.commit()
        finally:
            db.close()

    resp = client.post(f"/api/v1/connectors/{cid}/sync", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["datasets_total"] == 2
    assert body["datasets_synced"] == 2
    assert body["datasets_failed"] == 0
    assert body["total_rows"] == 6  # 3 rows per dataset
    assert body["kpi_generation_triggered"] == 0  # existing KPIs → skipped
    assert all(r["status"] == "success" and r["row_count"] == 3 for r in body["results"])

    # The real sync wrote per-dataset sync-log rows (not a connection test).
    logs = client.get(f"/api/v1/connectors/{cid}/sync-logs", headers=headers).json()
    assert len([entry for entry in logs if entry["status"] == "success"]) >= 2
