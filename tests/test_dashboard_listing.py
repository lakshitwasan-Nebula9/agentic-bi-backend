"""Dashboard listing metadata + View-KPIs + Duplicate service behavior.

Seeds a connector -> dataset -> two certified KPIs and a dashboard (owned by a
manager) with one widget per KPI, then exercises the listing metadata, the
per-dashboard KPI lookup, and duplication (including by a higher-ranked viewer
who is not the owner). Rows are uniquely suffixed and cleaned up in teardown.
"""

import uuid
from datetime import UTC, datetime

import pytest


@pytest.fixture
def seeded_dashboard():
    from app.core.database import SessionLocal
    from app.models.connector import DataConnector
    from app.models.dashboard import Dashboard, DashboardWidget
    from app.models.dataset import Dataset
    from app.models.kpi import KPIDefinition
    from app.models.user import User, UserRole

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    owner = User(
        email=f"dash-owner-{suffix}@example.com",
        name="Dash Owner",
        hashed_password="x",
        role=UserRole.MANAGER,
    )
    viewer = User(
        email=f"dash-viewer-{suffix}@example.com",
        name="Dash Viewer",
        hashed_password="x",
        role=UserRole.EXECUTIVE,  # ranks above manager -> implicit read access
    )
    db.add_all([owner, viewer])
    db.flush()

    connector = DataConnector(
        name=f"conn-{suffix}",
        host="localhost",
        database_name="sales_db",
        username="u",
        encrypted_password="x",
    )
    db.add(connector)
    db.flush()
    dataset = Dataset(
        connector_id=connector.id,
        name=f"ds-{suffix}",
        source_query="SELECT * FROM orders",
        last_synced_at=datetime.now(UTC),
    )
    db.add(dataset)
    db.flush()

    kpis = []
    for tag in ("a", "b"):
        kpi = KPIDefinition(
            dataset_id=dataset.id,
            table_name="orders",
            name=f"kpi-{tag}-{suffix}",
            display_name=f"KPI {tag}",
            description="d",
            category="revenue",
            formula="SUM(x)",
            sql_expression="SUM(x)",
            direction="up_is_good",
            status="certified",
            certified_at=datetime.now(UTC),
        )
        db.add(kpi)
        kpis.append(kpi)
    db.flush()

    dashboard = Dashboard(owner_id=owner.id, name=f"Sales-{suffix}", category="revenue")
    db.add(dashboard)
    db.flush()
    for kpi in kpis:
        db.add(
            DashboardWidget(
                dashboard_id=dashboard.id,
                widget_type="kpi_tile",
                title=kpi.display_name,
                config={"kpi_id": str(kpi.id)},
            )
        )
    db.commit()

    ids = {
        "owner": owner,
        "viewer": viewer,
        "dashboard_id": dashboard.id,
        "dashboard_name": dashboard.name,
        "kpi_ids": {k.id for k in kpis},
    }
    yield db, ids

    # Delete widgets + dashboards owned by either test user (covers duplicates),
    # then the KPI graph and the users.
    owner_ids = [owner.id, viewer.id]
    dash_rows = db.query(Dashboard).filter(Dashboard.owner_id.in_(owner_ids)).all()
    for d in dash_rows:
        db.query(DashboardWidget).filter(DashboardWidget.dashboard_id == d.id).delete()
    db.query(Dashboard).filter(Dashboard.owner_id.in_(owner_ids)).delete()
    db.commit()
    for kpi in kpis:
        db.query(KPIDefinition).filter(KPIDefinition.id == kpi.id).delete()
    db.query(Dataset).filter(Dataset.id == dataset.id).delete()
    db.query(DataConnector).filter(DataConnector.id == connector.id).delete()
    db.query(User).filter(User.id.in_(owner_ids)).delete()
    db.commit()
    db.close()


def test_list_dashboards_includes_metadata(seeded_dashboard):
    from app.services import dashboard_service

    db, ids = seeded_dashboard
    rows = dashboard_service.list_dashboards(db, ids["owner"])
    row = next(d for d in rows if d.id == ids["dashboard_id"])
    assert row.widget_count == 2
    assert row.kpi_count == 2
    assert row.owner_name == "Dash Owner"


def test_kpis_for_dashboard_returns_widget_kpis(seeded_dashboard):
    from app.services import dashboard_service

    db, ids = seeded_dashboard
    kpis = dashboard_service.kpis_for_dashboard(db, ids["dashboard_id"], ids["owner"])
    assert {k.id for k in kpis} == ids["kpi_ids"]


def test_duplicate_dashboard_copies_widgets(seeded_dashboard):
    from app.models.dashboard import DashboardWidget
    from app.services import dashboard_service

    db, ids = seeded_dashboard
    copy = dashboard_service.duplicate_dashboard(db, ids["dashboard_id"], ids["owner"])
    assert copy.id != ids["dashboard_id"]
    assert copy.name == f"Copy of {ids['dashboard_name']}"
    assert copy.owner_id == ids["owner"].id
    assert copy.is_default is False
    widget_count = db.query(DashboardWidget).filter(DashboardWidget.dashboard_id == copy.id).count()
    assert widget_count == 2


def test_non_owner_viewer_can_duplicate(seeded_dashboard):
    from app.services import dashboard_service

    db, ids = seeded_dashboard
    copy = dashboard_service.duplicate_dashboard(db, ids["dashboard_id"], ids["viewer"])
    assert copy.owner_id == ids["viewer"].id
    assert copy.owner_id != ids["owner"].id


def test_non_owner_viewer_can_pin(seeded_dashboard):
    from app.services import dashboard_service

    db, ids = seeded_dashboard
    # A viewer with only read access (not the owner) can still pin/unpin.
    pinned = dashboard_service.set_pinned(db, ids["dashboard_id"], ids["viewer"], True)
    assert pinned.is_default is True
    unpinned = dashboard_service.set_pinned(db, ids["dashboard_id"], ids["viewer"], False)
    assert unpinned.is_default is False
