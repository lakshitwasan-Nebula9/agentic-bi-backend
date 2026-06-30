import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crud import dashboard as dashboard_crud
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition, KPISnapshot
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardUpdate,
    WidgetCreate,
    WidgetLayoutUpdate,
    WidgetUpdate,
)
from app.schemas.kpi import KPIResponse
from app.services import kpi_service

# Number of certified KPIs to seed a preconfigured dashboard with.
_PRECONFIG_KPI_LIMIT = 8

# Headline scalar KPIs kept as number tiles before time-series KPIs get
# promoted to charts — keeps the top of the dashboard scannable.
_TILE_QUOTA = 3

# Monthly snapshots a KPI needs before a line chart is worth rendering.
_MIN_SERIES_POINTS = 3

# react-grid-layout sizing (12-column grid).
_TILE_W, _TILE_H = 3, 3
_CHART_W, _CHART_H = 6, 5
_GRID_COLS = 12


def get_owned_dashboard_or_404(
    db: Session, dashboard_id: uuid.UUID, owner_id: uuid.UUID
) -> Dashboard:
    dashboard = dashboard_crud.get_dashboard(db, dashboard_id)
    if dashboard is None or dashboard.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    return dashboard


def list_dashboards(db: Session, owner_id: uuid.UUID) -> list[Dashboard]:
    return dashboard_crud.list_dashboards(db, owner_id)


def create_dashboard(db: Session, payload: DashboardCreate, owner_id: uuid.UUID) -> Dashboard:
    dashboard = Dashboard(
        name=payload.name,
        description=payload.description,
        is_default=payload.is_default,
        owner_id=owner_id,
    )
    dashboard = dashboard_crud.create_dashboard(db, dashboard)
    if payload.connector_id is not None:
        _preconfigure_widgets(db, dashboard, payload.connector_id)
    return dashboard


def _certified_kpis_for_connector(db: Session, connector_id: uuid.UUID) -> list[KPIDefinition]:
    """Most-recently-certified live KPIs reachable from the connector's datasets."""
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
        .limit(_PRECONFIG_KPI_LIMIT)
        .all()
    )


def _monthly_snapshot_counts(db: Session, kpi_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Live monthly-snapshot count per KPI (period_start set)."""
    if not kpi_ids:
        return {}
    rows = (
        db.query(KPISnapshot.kpi_id, func.count())
        .filter(
            KPISnapshot.kpi_id.in_(kpi_ids),
            KPISnapshot.is_deleted.is_(False),
            KPISnapshot.period_start.isnot(None),
        )
        .group_by(KPISnapshot.kpi_id)
        .all()
    )
    return {kpi_id: count for kpi_id, count in rows}


def _widget_type_for(kpi: KPIDefinition, has_series: bool, tiles_placed: int, promoted: int) -> str:
    """Pick a widget type for a preconfigured KPI.

    Explicit `line`/`bar` suggestions win. Otherwise the first few KPIs stay as
    headline number tiles; beyond that, any KPI with a usable monthly time
    series is promoted to a chart so the dashboard isn't all tiles. Promoted
    charts alternate line/bar for visual variety.
    """
    chart = (kpi.suggested_chart or "").lower()
    if chart == "line":
        return "line_chart"
    if chart == "bar":
        return "bar_chart"
    if has_series and tiles_placed >= _TILE_QUOTA:
        return "bar_chart" if promoted % 2 else "line_chart"
    return "kpi_tile"


def _build_widget_config(kpi: KPIDefinition, widget_type: str, enriched: KPIResponse) -> dict:
    if widget_type == "kpi_tile":
        return {
            "kpi_id": str(kpi.id),
            "value": enriched.current_value if enriched.current_value is not None else "—",
            "label": kpi.display_name or kpi.name,
            "trend": enriched.mom_change_pct if enriched.mom_change_pct is not None else 0,
            "subtitle": kpi.category,
            "unit": kpi.unit or "",
        }
    return {"kpi_id": str(kpi.id)}


def _preconfigure_widgets(db: Session, dashboard: Dashboard, connector_id: uuid.UUID) -> None:
    kpis = _certified_kpis_for_connector(db, connector_id)
    if not kpis:
        return

    enriched_by_id = {e.id: e for e in kpi_service._enrich(db, kpis)}
    series_counts = _monthly_snapshot_counts(db, [k.id for k in kpis])

    widgets: list[DashboardWidget] = []
    cursor_x = 0
    cursor_y = 0
    row_h = 0
    tiles_placed = 0
    promoted = 0
    for kpi in kpis:
        has_series = series_counts.get(kpi.id, 0) >= _MIN_SERIES_POINTS
        widget_type = _widget_type_for(kpi, has_series, tiles_placed, promoted)
        chart_hint = (kpi.suggested_chart or "").lower()
        if widget_type == "kpi_tile":
            tiles_placed += 1
        elif chart_hint not in ("line", "bar"):
            promoted += 1
        w, h = (_TILE_W, _TILE_H) if widget_type == "kpi_tile" else (_CHART_W, _CHART_H)
        if cursor_x + w > _GRID_COLS:
            cursor_x = 0
            cursor_y += row_h
            row_h = 0
        widgets.append(
            DashboardWidget(
                dashboard_id=dashboard.id,
                widget_type=widget_type,
                title=kpi.display_name or kpi.name,
                config=_build_widget_config(kpi, widget_type, enriched_by_id[kpi.id]),
                x=cursor_x,
                y=cursor_y,
                w=w,
                h=h,
            )
        )
        cursor_x += w
        row_h = max(row_h, h)

    dashboard_crud.create_widgets(db, widgets)
    db.refresh(dashboard)


def update_dashboard(
    db: Session, dashboard_id: uuid.UUID, payload: DashboardUpdate, owner_id: uuid.UUID
) -> Dashboard:
    dashboard = get_owned_dashboard_or_404(db, dashboard_id, owner_id)
    updates = payload.model_dump(exclude_unset=True)
    return dashboard_crud.update_dashboard(db, dashboard, updates)


def delete_dashboard(db: Session, dashboard_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    dashboard = get_owned_dashboard_or_404(db, dashboard_id, owner_id)
    dashboard_crud.delete_dashboard(db, dashboard)


def add_widget(
    db: Session, dashboard_id: uuid.UUID, payload: WidgetCreate, owner_id: uuid.UUID
) -> DashboardWidget:
    get_owned_dashboard_or_404(db, dashboard_id, owner_id)
    widget = DashboardWidget(dashboard_id=dashboard_id, **payload.model_dump())
    return dashboard_crud.create_widget(db, widget)


def get_owned_widget_or_404(
    db: Session, dashboard_id: uuid.UUID, widget_id: uuid.UUID, owner_id: uuid.UUID
) -> DashboardWidget:
    get_owned_dashboard_or_404(db, dashboard_id, owner_id)
    widget = dashboard_crud.get_widget(db, widget_id)
    if widget is None or widget.dashboard_id != dashboard_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
    return widget


def update_widget(
    db: Session,
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    owner_id: uuid.UUID,
) -> DashboardWidget:
    widget = get_owned_widget_or_404(db, dashboard_id, widget_id, owner_id)
    updates = payload.model_dump(exclude_unset=True)
    return dashboard_crud.update_widget(db, widget, updates)


def delete_widget(
    db: Session, dashboard_id: uuid.UUID, widget_id: uuid.UUID, owner_id: uuid.UUID
) -> None:
    widget = get_owned_widget_or_404(db, dashboard_id, widget_id, owner_id)
    dashboard_crud.delete_widget(db, widget)


def save_layout(
    db: Session, dashboard_id: uuid.UUID, layout: list[WidgetLayoutUpdate], owner_id: uuid.UUID
) -> Dashboard:
    dashboard = get_owned_dashboard_or_404(db, dashboard_id, owner_id)
    widgets_by_id = {widget.id: widget for widget in dashboard.widgets}

    for entry in layout:
        widget = widgets_by_id.get(entry.id)
        if widget is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Widget {entry.id} not found on this dashboard",
            )
        widget.x = entry.x
        widget.y = entry.y
        widget.w = entry.w
        widget.h = entry.h

    db.commit()
    db.refresh(dashboard)
    return dashboard
