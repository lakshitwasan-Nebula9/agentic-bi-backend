import uuid

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.dashboard import Dashboard
from app.models.user import User, UserRole

client = TestClient(app)


def _signup_role(role: UserRole) -> tuple[str, str, str]:
    """Sign up a user, force its role in the DB, return (token, email, user_id)."""
    email = f"dashperm-{role.value}-{uuid.uuid4().hex}@example.com"
    resp = client.post("/api/v1/auth/signup", json={"email": email, "password": "password123"})
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if role != UserRole.ANALYST:
            user.role = role
            db.commit()
        user_id = str(user.id)
    finally:
        db.close()
    return token, email, user_id


def _cleanup(dashboard_ids: list[str], emails: list[str]) -> None:
    db = SessionLocal()
    try:
        if dashboard_ids:
            db.query(Dashboard).filter(Dashboard.id.in_(dashboard_ids)).delete(
                synchronize_session=False
            )
        if emails:
            db.query(User).filter(User.email.in_(emails)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_dashboard(token: str, name: str) -> dict:
    resp = client.post("/api/v1/dashboards", json={"name": name}, headers=_auth(token))
    assert resp.status_code == 201
    return resp.json()


def _grant(owner_token: str, dashboard_id: str, user_id: str, level: str) -> dict:
    resp = client.put(
        f"/api/v1/dashboards/{dashboard_id}/permissions/{user_id}",
        json={"access_level": level},
        headers=_auth(owner_token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestReadGrant:
    def test_peer_analyst_read_grant(self):
        owner_token, owner_email, _ = _signup_role(UserRole.ANALYST)
        peer_token, peer_email, peer_id = _signup_role(UserRole.ANALYST)
        dash = _create_dashboard(owner_token, f"perm-read-{uuid.uuid4().hex}")
        try:
            # Without a grant a peer analyst can't even see it.
            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(peer_token))
            assert resp.status_code == 404

            grant = _grant(owner_token, dash["id"], peer_id, "read")
            assert grant["access_level"] == "read"
            assert grant["user_email"] == peer_email

            # Read works and reports read-only access.
            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(peer_token))
            assert resp.status_code == 200
            assert resp.json()["my_access"] == "read"

            # Shared dashboard shows up in the peer's list.
            resp = client.get("/api/v1/dashboards", headers=_auth(peer_token))
            assert dash["id"] in [d["id"] for d in resp.json()]

            # Writes are rejected (403 — visible but not editable).
            resp = client.patch(
                f"/api/v1/dashboards/{dash['id']}",
                json={"name": "hijacked"},
                headers=_auth(peer_token),
            )
            assert resp.status_code == 403
            resp = client.post(
                f"/api/v1/dashboards/{dash['id']}/widgets",
                json={"widget_type": "kpi_tile"},
                headers=_auth(peer_token),
            )
            assert resp.status_code == 403

            # Read grantees can't manage the permissions panel either.
            resp = client.get(
                f"/api/v1/dashboards/{dash['id']}/permissions", headers=_auth(peer_token)
            )
            assert resp.status_code == 403
        finally:
            _cleanup([dash["id"]], [owner_email, peer_email])


class TestWriteGrant:
    def test_write_grant_edits_but_cannot_delete(self):
        owner_token, owner_email, _ = _signup_role(UserRole.ANALYST)
        editor_token, editor_email, editor_id = _signup_role(UserRole.ANALYST)
        dash = _create_dashboard(owner_token, f"perm-write-{uuid.uuid4().hex}")
        try:
            _grant(owner_token, dash["id"], editor_id, "write")

            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(editor_token))
            assert resp.status_code == 200
            assert resp.json()["my_access"] == "write"

            # Rename, add / update widget, save layout.
            resp = client.patch(
                f"/api/v1/dashboards/{dash['id']}",
                json={"name": "renamed-by-editor"},
                headers=_auth(editor_token),
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "renamed-by-editor"

            resp = client.post(
                f"/api/v1/dashboards/{dash['id']}/widgets",
                json={"widget_type": "kpi_tile", "title": "shared widget"},
                headers=_auth(editor_token),
            )
            assert resp.status_code == 201
            widget_id = resp.json()["id"]

            resp = client.patch(
                f"/api/v1/dashboards/{dash['id']}/widgets/{widget_id}",
                json={"title": "updated"},
                headers=_auth(editor_token),
            )
            assert resp.status_code == 200

            resp = client.put(
                f"/api/v1/dashboards/{dash['id']}/layout",
                json=[{"id": widget_id, "x": 1, "y": 2, "w": 3, "h": 4}],
                headers=_auth(editor_token),
            )
            assert resp.status_code == 200

            # Delete stays owner-only.
            resp = client.delete(f"/api/v1/dashboards/{dash['id']}", headers=_auth(editor_token))
            assert resp.status_code == 404

            resp = client.delete(
                f"/api/v1/dashboards/{dash['id']}/widgets/{widget_id}",
                headers=_auth(editor_token),
            )
            assert resp.status_code == 204
        finally:
            _cleanup([dash["id"]], [owner_email, editor_email])

    def test_write_grantee_can_manage_permissions(self):
        owner_token, owner_email, _ = _signup_role(UserRole.ANALYST)
        editor_token, editor_email, editor_id = _signup_role(UserRole.ANALYST)
        third_token, third_email, third_id = _signup_role(UserRole.ANALYST)
        dash = _create_dashboard(owner_token, f"perm-manage-{uuid.uuid4().hex}")
        try:
            _grant(owner_token, dash["id"], editor_id, "write")

            # Write grantee shares the dashboard with a third user.
            grant = _grant(editor_token, dash["id"], third_id, "read")
            assert grant["access_level"] == "read"

            resp = client.get(
                f"/api/v1/dashboards/{dash['id']}/permissions", headers=_auth(editor_token)
            )
            assert resp.status_code == 200
            assert {g["user_id"] for g in resp.json()} == {editor_id, third_id}

            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(third_token))
            assert resp.status_code == 200

            # And revokes it again.
            resp = client.delete(
                f"/api/v1/dashboards/{dash['id']}/permissions/{third_id}",
                headers=_auth(editor_token),
            )
            assert resp.status_code == 204
            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(third_token))
            assert resp.status_code == 404
        finally:
            _cleanup([dash["id"]], [owner_email, editor_email, third_email])


class TestHierarchyInteraction:
    def test_manager_hierarchy_read_unchanged(self):
        analyst_token, analyst_email, _ = _signup_role(UserRole.ANALYST)
        manager_token, manager_email, _ = _signup_role(UserRole.MANAGER)
        dash = _create_dashboard(analyst_token, f"perm-hier-{uuid.uuid4().hex}")
        try:
            # No grant needed: hierarchy still gives the manager read-only access.
            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(manager_token))
            assert resp.status_code == 200
            assert resp.json()["my_access"] == "read"

            resp = client.patch(
                f"/api/v1/dashboards/{dash['id']}",
                json={"name": "manager-edit"},
                headers=_auth(manager_token),
            )
            assert resp.status_code == 403
        finally:
            _cleanup([dash["id"]], [analyst_email, manager_email])

    def test_write_grant_upgrades_manager(self):
        analyst_token, analyst_email, _ = _signup_role(UserRole.ANALYST)
        manager_token, manager_email, manager_id = _signup_role(UserRole.MANAGER)
        dash = _create_dashboard(analyst_token, f"perm-upgrade-{uuid.uuid4().hex}")
        try:
            _grant(analyst_token, dash["id"], manager_id, "write")
            resp = client.patch(
                f"/api/v1/dashboards/{dash['id']}",
                json={"name": "manager-can-edit-now"},
                headers=_auth(manager_token),
            )
            assert resp.status_code == 200
            assert resp.json()["my_access"] == "write"
        finally:
            _cleanup([dash["id"]], [analyst_email, manager_email])


class TestGrantLifecycle:
    def test_upsert_revoke_and_owner_guard(self):
        owner_token, owner_email, owner_id = _signup_role(UserRole.ANALYST)
        peer_token, peer_email, peer_id = _signup_role(UserRole.ANALYST)
        dash = _create_dashboard(owner_token, f"perm-lifecycle-{uuid.uuid4().hex}")
        try:
            # Grant read, then upsert to write — same row, new level.
            first = _grant(owner_token, dash["id"], peer_id, "read")
            second = _grant(owner_token, dash["id"], peer_id, "write")
            assert first["id"] == second["id"]
            assert second["access_level"] == "write"

            # Owner can't be granted onto their own dashboard.
            resp = client.put(
                f"/api/v1/dashboards/{dash['id']}/permissions/{owner_id}",
                json={"access_level": "read"},
                headers=_auth(owner_token),
            )
            assert resp.status_code == 400

            # Invalid level rejected by the schema.
            resp = client.put(
                f"/api/v1/dashboards/{dash['id']}/permissions/{peer_id}",
                json={"access_level": "admin"},
                headers=_auth(owner_token),
            )
            assert resp.status_code == 422

            # Revoke removes all access for a peer analyst.
            resp = client.delete(
                f"/api/v1/dashboards/{dash['id']}/permissions/{peer_id}",
                headers=_auth(owner_token),
            )
            assert resp.status_code == 204
            resp = client.get(f"/api/v1/dashboards/{dash['id']}", headers=_auth(peer_token))
            assert resp.status_code == 404

            # Revoking a non-existent grant → 404.
            resp = client.delete(
                f"/api/v1/dashboards/{dash['id']}/permissions/{peer_id}",
                headers=_auth(owner_token),
            )
            assert resp.status_code == 404
        finally:
            _cleanup([dash["id"]], [owner_email, peer_email])

    def test_owner_sees_write_access_in_list(self):
        owner_token, owner_email, _ = _signup_role(UserRole.ANALYST)
        dash = _create_dashboard(owner_token, f"perm-myaccess-{uuid.uuid4().hex}")
        try:
            resp = client.get("/api/v1/dashboards", headers=_auth(owner_token))
            mine = next(d for d in resp.json() if d["id"] == dash["id"])
            assert mine["my_access"] == "write"
        finally:
            _cleanup([dash["id"]], [owner_email])


class TestPermissionChangeStream:
    def test_grant_and_revoke_publish_redis_events(self):
        """Grants/revokes must land on the dashboard_permission_changed stream
        so the SSE endpoint can push them to the affected user."""
        import json

        from app.agents.messaging import DASHBOARD_PERMISSION_CHANGED, get_redis_client, stream_name

        owner_token, owner_email, _ = _signup_role(UserRole.ANALYST)
        peer_token, peer_email, peer_id = _signup_role(UserRole.ANALYST)
        dash = _create_dashboard(owner_token, f"perm-stream-{uuid.uuid4().hex}")
        redis_client = get_redis_client()
        stream = stream_name(DASHBOARD_PERMISSION_CHANGED)

        def _events_for_dashboard() -> list[dict]:
            entries = redis_client.xrevrange(stream, count=50)
            payloads = [json.loads(fields["payload"]) for _id, fields in entries]
            return [p for p in payloads if p["dashboard_id"] == dash["id"]]

        try:
            _grant(owner_token, dash["id"], peer_id, "read")
            events = _events_for_dashboard()
            assert events, "grant did not publish a permission-change event"
            assert events[0] == {
                "dashboard_id": dash["id"],
                "user_id": peer_id,
                "access_level": "read",
            }

            resp = client.delete(
                f"/api/v1/dashboards/{dash['id']}/permissions/{peer_id}",
                headers=_auth(owner_token),
            )
            assert resp.status_code == 204
            events = _events_for_dashboard()
            assert events[0] == {
                "dashboard_id": dash["id"],
                "user_id": peer_id,
                "access_level": None,
            }
        finally:
            _cleanup([dash["id"]], [owner_email, peer_email])

    def test_stream_endpoint_requires_auth(self):
        resp = client.get("/api/v1/dashboards/stream")
        assert resp.status_code == 401
