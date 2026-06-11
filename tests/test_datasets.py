import uuid
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.main import app

client = TestClient(app)


def _signup_and_get_token() -> str:
    email = f"dataset-test-{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_self_connector(headers: dict[str, str]) -> str:
    """Register a connector pointing back at the app's own database."""
    parsed = urlparse(settings.DATABASE_URL)

    response = client.post(
        "/api/v1/connectors",
        headers=headers,
        json={
            "name": f"self-source-{uuid.uuid4().hex}",
            "host": parsed.hostname,
            "port": parsed.port or 5432,
            "database_name": parsed.path.lstrip("/"),
            "username": parsed.username,
            "password": parsed.password,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_dataset_preview_and_sync_flow():
    token = _signup_and_get_token()
    headers = _auth_headers(token)
    connector_id = _create_self_connector(headers)

    table_name = f"test_sales_{uuid.uuid4().hex}"
    db = SessionLocal()
    try:
        db.execute(
            text(f"CREATE TABLE {table_name} (id INT, region TEXT, amount NUMERIC, sold_at DATE)")
        )
        db.execute(
            text(
                f"INSERT INTO {table_name} (id, region, amount, sold_at) VALUES "
                "(1, 'north', 1200.50, '2026-05-01'), "
                "(2, 'south', 800.00, '2026-05-02'), "
                "(3, 'east', 1500.75, '2026-05-03'), "
                "(4, 'west', 950.25, '2026-05-04')"
            )
        )
        db.commit()

        create_response = client.post(
            "/api/v1/datasets",
            headers=headers,
            json={
                "name": f"sales-{uuid.uuid4().hex}",
                "connector_id": connector_id,
                "source_query": f"SELECT * FROM {table_name}",
            },
        )
        assert create_response.status_code == 201
        dataset = create_response.json()
        dataset_id = dataset["id"]
        assert dataset["row_count"] == 0
        assert dataset["last_synced_at"] is None

        preview_response = client.get(f"/api/v1/datasets/{dataset_id}/preview", headers=headers)
        assert preview_response.status_code == 200
        preview = preview_response.json()
        assert set(preview["columns"]) == {"id", "region", "amount", "sold_at"}
        assert len(preview["rows"]) == 4

        sync_response = client.post(f"/api/v1/datasets/{dataset_id}/sync", headers=headers)
        assert sync_response.status_code == 200
        sync_result = sync_response.json()
        assert sync_result["row_count"] == 4
        assert set(sync_result["schema_fingerprint"].keys()) == {
            "id",
            "region",
            "amount",
            "sold_at",
        }

        get_response = client.get(f"/api/v1/datasets/{dataset_id}", headers=headers)
        assert get_response.status_code == 200
        assert get_response.json()["row_count"] == 4
        assert get_response.json()["last_synced_at"] is not None

        records_response = client.get(f"/api/v1/datasets/{dataset_id}/records", headers=headers)
        assert records_response.status_code == 200
        records = records_response.json()
        assert len(records) == 4
        assert {row["row_data"]["region"] for row in records} == {"north", "south", "east", "west"}

        # re-syncing should replace records, not duplicate them
        resync_response = client.post(f"/api/v1/datasets/{dataset_id}/sync", headers=headers)
        assert resync_response.status_code == 200
        assert resync_response.json()["row_count"] == 4
        records_after_resync = client.get(f"/api/v1/datasets/{dataset_id}/records", headers=headers)
        assert len(records_after_resync.json()) == 4

        delete_response = client.delete(f"/api/v1/datasets/{dataset_id}", headers=headers)
        assert delete_response.status_code == 204

        get_after_delete = client.get(f"/api/v1/datasets/{dataset_id}", headers=headers)
        assert get_after_delete.status_code == 404
    finally:
        db.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        db.commit()
        db.close()

    cleanup_response = client.delete(f"/api/v1/connectors/{connector_id}", headers=headers)
    assert cleanup_response.status_code == 204


def test_dataset_create_rejects_unknown_connector():
    token = _signup_and_get_token()
    headers = _auth_headers(token)

    response = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "name": f"orphan-{uuid.uuid4().hex}",
            "connector_id": str(uuid.uuid4()),
            "source_query": "SELECT 1",
        },
    )
    assert response.status_code == 404


def test_dataset_requires_authentication():
    response = client.get("/api/v1/datasets")
    assert response.status_code in (401, 403)
