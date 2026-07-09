"""Scope filtering for report generation.

Seeds two independent connector -> dataset -> certified-KPI graphs (with snapshots)
and one dashboard whose single widget references only the first KPI, then drives
``report_generation_service.generate_report`` in each scope and asserts the KPI
scorecard is filtered accordingly. Also covers the request-schema guard that at
most one scope id may be supplied. Rows are uniquely suffixed and cleaned up.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest


@pytest.fixture
def seeded_scope_graph():
    """Two connectors each with a certified KPI + snapshot; a dashboard on KPI A."""
    from app.core.database import SessionLocal
    from app.models.connector import DataConnector
    from app.models.dashboard import Dashboard, DashboardWidget
    from app.models.dataset import Dataset
    from app.models.kpi import KPIDefinition, KPISnapshot
    from app.models.user import User, UserRole

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]

    owner = User(
        email=f"owner_{suffix}@example.com",
        name="Owner",
        hashed_password="x",
        role=UserRole.MANAGER,
    )
    db.add(owner)
    db.flush()

    def make_graph(tag: str) -> tuple[DataConnector, KPIDefinition]:
        connector = DataConnector(
            name=f"conn_{tag}_{suffix}",
            host="localhost",
            database_name="sales_db",
            username="u",
            encrypted_password="x",
        )
        db.add(connector)
        db.flush()
        dataset = Dataset(
            connector_id=connector.id,
            name=f"ds_{tag}_{suffix}",
            source_query="SELECT * FROM orders",
            quality_score=0.9,
            last_synced_at=datetime.now(UTC),
        )
        db.add(dataset)
        db.flush()
        kpi = KPIDefinition(
            dataset_id=dataset.id,
            table_name="orders",
            name=f"revenue_{tag}_{suffix}",
            display_name=f"Revenue {tag}",
            description="desc",
            category="revenue",
            formula="SUM(revenue)",
            sql_expression="SUM(revenue)",
            direction="up_is_good",
            status="certified",
            certified_at=datetime.now(UTC),
        )
        db.add(kpi)
        db.flush()
        db.add(
            KPISnapshot(
                kpi_id=kpi.id,
                dataset_id=dataset.id,
                value=1000.0,
                period_start=datetime.now(UTC),
            )
        )
        db.flush()
        return connector, kpi

    conn_a, kpi_a = make_graph("a")
    conn_b, kpi_b = make_graph("b")

    dashboard = Dashboard(owner_id=owner.id, name=f"dash_{suffix}")
    db.add(dashboard)
    db.flush()
    db.add(
        DashboardWidget(
            dashboard_id=dashboard.id,
            widget_type="kpi",
            title="A",
            config={"kpi_id": str(kpi_a.id)},
        )
    )
    db.commit()

    ids = {
        "owner_id": owner.id,
        "dashboard_id": dashboard.id,
        "connector_a": conn_a.id,
        "connector_b": conn_b.id,
        "kpi_a": kpi_a.id,
        "kpi_b": kpi_b.id,
    }
    yield db, ids

    # Clean up children -> parents (no ORM cascade across raw FKs here).
    db.query(DashboardWidget).filter(DashboardWidget.dashboard_id == dashboard.id).delete()
    db.query(Dashboard).filter(Dashboard.id == dashboard.id).delete()
    db.commit()
    for kpi_id, ds_id, conn_id in (
        (kpi_a.id, kpi_a.dataset_id, conn_a.id),
        (kpi_b.id, kpi_b.dataset_id, conn_b.id),
    ):
        db.query(KPISnapshot).filter(KPISnapshot.kpi_id == kpi_id).delete()
        db.query(KPIDefinition).filter(KPIDefinition.id == kpi_id).delete()
        db.query(Dataset).filter(Dataset.id == ds_id).delete()
        db.query(DataConnector).filter(DataConnector.id == conn_id).delete()
    db.query(User).filter(User.id == owner.id).delete()
    db.commit()
    db.close()


def _run_report(db, **scope_kwargs) -> set[uuid.UUID]:
    """Generate a report with the given scope; return the KPI ids in its scorecard."""
    from app.crud import report as report_crud
    from app.models.report import Report
    from app.services.report_generation_service import generate_report

    report = Report(title="t", period_label="July 2026", status="generating")
    report_crud.create_report(db, report)
    report_id = report.id
    try:
        asyncio.run(generate_report(db, report_id, "t", "July 2026", **scope_kwargs))
        db.refresh(report)
        assert report.status == "ready"
        return {uuid.UUID(item["kpi_id"]) for item in report.report_json["kpi_scorecard"]}
    finally:
        db.query(Report).filter(Report.id == report_id).delete()
        db.commit()


def test_dashboard_scope_limits_to_dashboard_kpis(seeded_scope_graph):
    db, ids = seeded_scope_graph
    kpi_ids = _run_report(db, scope="dashboard", dashboard_id=ids["dashboard_id"])
    assert ids["kpi_a"] in kpi_ids
    assert ids["kpi_b"] not in kpi_ids


def test_database_scope_limits_to_connector_kpis(seeded_scope_graph):
    db, ids = seeded_scope_graph
    kpi_ids = _run_report(db, scope="database", connector_id=ids["connector_b"])
    assert ids["kpi_b"] in kpi_ids
    assert ids["kpi_a"] not in kpi_ids


def test_global_scope_includes_all_certified_kpis(seeded_scope_graph):
    db, ids = seeded_scope_graph
    kpi_ids = _run_report(db, scope="global")
    assert {ids["kpi_a"], ids["kpi_b"]}.issubset(kpi_ids)


def test_request_rejects_both_scope_ids():
    from pydantic import ValidationError

    from app.schemas.report import ReportGenerateRequest

    with pytest.raises(ValidationError):
        ReportGenerateRequest(dashboard_id=uuid.uuid4(), connector_id=uuid.uuid4())
