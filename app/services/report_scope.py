"""Scope-resolution helpers for report generation.

Reports can be pinned to a single dashboard (its widget KPIs) or a single
database/connector (all of its certified KPIs). These helpers translate a scope
id into the KPI set the report should cover, reusing the same join patterns as
``dashboard_service`` but kept here to avoid a circular import from
``report_generation_service``.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.dashboard import DashboardWidget
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition


def kpi_ids_for_dashboard(db: Session, dashboard_id: uuid.UUID) -> set[uuid.UUID]:
    """KPI ids referenced by a dashboard's widgets (via ``config->>'kpi_id'``)."""
    ids: set[uuid.UUID] = set()
    rows = (
        db.query(DashboardWidget.config["kpi_id"].astext)
        .filter(DashboardWidget.dashboard_id == dashboard_id)
        .all()
    )
    for (value,) in rows:
        if not value:
            continue
        try:
            ids.add(uuid.UUID(value))
        except (ValueError, AttributeError):
            continue
    return ids


def certified_kpis_for_connector(db: Session, connector_id: uuid.UUID) -> list[KPIDefinition]:
    """All live, certified KPIs reachable from a connector's datasets (uncapped)."""
    return (
        db.query(KPIDefinition)
        .join(Dataset, Dataset.id == KPIDefinition.dataset_id)
        .filter(
            Dataset.connector_id == connector_id,
            Dataset.is_deleted.is_(False),
            KPIDefinition.status == "certified",
            KPIDefinition.is_deleted.is_(False),
        )
        .order_by(KPIDefinition.certified_at.desc().nulls_last())
        .all()
    )
