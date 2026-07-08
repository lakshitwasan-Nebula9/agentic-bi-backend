import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.messaging import DASHBOARD_PERMISSION_CHANGED, AgentPublisher
from app.crud import dashboard as dashboard_crud
from app.crud import user as user_crud
from app.models.dashboard import Dashboard, DashboardPermission, DashboardWidget
from app.models.dataset import Dataset
from app.models.kpi import KPIDefinition, KPISnapshot
from app.models.user import ROLE_RANK, User, UserRole
from app.schemas.dashboard import (
    DashboardAccessLevel,
    DashboardCreate,
    DashboardPermissionResponse,
    DashboardUpdate,
    WidgetCreate,
    WidgetLayoutUpdate,
    WidgetUpdate,
)
from app.schemas.kpi import KPIResponse
from app.services import audit_service, kpi_service

logger = logging.getLogger(__name__)

_publisher = AgentPublisher()


def _publish_permission_change(
    dashboard_id: uuid.UUID, user_id: uuid.UUID, access_level: str | None
) -> None:
    """Best-effort: emit a permission change onto Redis for the SSE stream.

    access_level None means the grant was revoked. The grant itself is already
    persisted, so a broker hiccup is logged and swallowed — the affected user
    just falls back to picking the change up on their next refetch.
    """
    try:
        _publisher.publish(
            DASHBOARD_PERMISSION_CHANGED,
            {
                "dashboard_id": str(dashboard_id),
                "user_id": str(user_id),
                "access_level": access_level,
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to publish permission change for dashboard %s to Redis",
            dashboard_id,
            exc_info=True,
        )


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


def _lower_roles(viewer: User) -> list[UserRole]:
    """Roles strictly less senior than the viewer's (higher ROLE_RANK number)."""
    return [r for r in UserRole if ROLE_RANK[r] > ROLE_RANK[viewer.role]]


def get_effective_access(
    db: Session, dashboard: Dashboard, user: User
) -> DashboardAccessLevel | None:
    """Resolve a user's access to a dashboard.

    Owner → write. Otherwise the best of an explicit permission grant and the
    implicit role-hierarchy read (owner strictly lower-ranked than the viewer).
    None → no access (surfaced as 404 to avoid leaking dashboard existence).
    """
    if dashboard.owner_id == user.id:
        return DashboardAccessLevel.WRITE
    grant = dashboard_crud.get_permission(db, dashboard.id, user.id)
    if grant is not None and grant.access_level == DashboardAccessLevel.WRITE:
        return DashboardAccessLevel.WRITE
    if grant is not None:
        return DashboardAccessLevel.READ
    owner = user_crud.get_user_by_id(db, dashboard.owner_id)
    if owner is not None and ROLE_RANK[owner.role] > ROLE_RANK[user.role]:
        return DashboardAccessLevel.READ
    return None


def _with_access(dashboard: Dashboard, access: DashboardAccessLevel | None) -> Dashboard:
    """Attach the caller's effective access so DashboardResponse.my_access picks
    it up via from_attributes (plain instance attribute, not a column)."""
    dashboard.my_access = access
    return dashboard


def get_viewable_dashboard_or_404(db: Session, dashboard_id: uuid.UUID, viewer: User) -> Dashboard:
    dashboard = dashboard_crud.get_dashboard(db, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    access = get_effective_access(db, dashboard, viewer)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    return _with_access(dashboard, access)


def get_writable_dashboard_or_404(db: Session, dashboard_id: uuid.UUID, actor: User) -> Dashboard:
    """Write access: the owner or a user holding an explicit write grant.

    No access at all → 404 (as everywhere); read-only access → 403 so the
    caller knows the dashboard exists but is not theirs to edit.
    """
    dashboard = dashboard_crud.get_dashboard(db, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    access = get_effective_access(db, dashboard, actor)
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found")
    if access != DashboardAccessLevel.WRITE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have write access to this dashboard",
        )
    return _with_access(dashboard, access)


def list_dashboards(db: Session, viewer: User) -> list[Dashboard]:
    dashboards = dashboard_crud.list_viewable_dashboards(db, viewer.id, _lower_roles(viewer))
    grants = {
        g.dashboard_id: g.access_level
        for g in db.query(DashboardPermission).filter(DashboardPermission.user_id == viewer.id)
    }
    for dashboard in dashboards:
        if dashboard.owner_id == viewer.id:
            access = DashboardAccessLevel.WRITE
        elif grants.get(dashboard.id) == DashboardAccessLevel.WRITE:
            access = DashboardAccessLevel.WRITE
        else:
            access = DashboardAccessLevel.READ
        _with_access(dashboard, access)
    return dashboards


def create_dashboard(db: Session, payload: DashboardCreate, owner_id: uuid.UUID) -> Dashboard:
    # An explicit category wins; otherwise infer it from the linked data source so
    # the dashboard files itself under the domain of the DB it was built from.
    category = payload.category
    if category is None and payload.connector_id is not None:
        category = _dominant_kpi_category(db, payload.connector_id)

    dashboard = Dashboard(
        name=payload.name,
        description=payload.description,
        category=category,
        is_default=payload.is_default,
        owner_id=owner_id,
    )
    dashboard = dashboard_crud.create_dashboard(db, dashboard)
    if payload.connector_id is not None:
        _preconfigure_widgets(db, dashboard, payload.connector_id)
    return _with_access(dashboard, DashboardAccessLevel.WRITE)


def _widget_kpi_ids(db: Session, dashboard_id: uuid.UUID) -> list[uuid.UUID]:
    """KPI ids referenced by a dashboard's widgets (via ``config->>'kpi_id'``)."""
    ids: list[uuid.UUID] = []
    rows = (
        db.query(DashboardWidget.config["kpi_id"].astext)
        .filter(DashboardWidget.dashboard_id == dashboard_id)
        .all()
    )
    for (value,) in rows:
        if not value:
            continue
        try:
            ids.append(uuid.UUID(value))
        except (ValueError, AttributeError):
            continue
    return ids


def _dominant_category_from_widgets(db: Session, dashboard_id: uuid.UUID) -> str | None:
    """Most common KPI category among the KPIs actually placed on the dashboard.

    Unlike the connector lookup this needs no stored source link, so it also works
    for dashboards created before category auto-assignment (see backfill_categories).
    Ties broken alphabetically; None when no widget maps to a categorized KPI.
    """
    kpi_ids = _widget_kpi_ids(db, dashboard_id)
    if not kpi_ids:
        return None
    row = (
        db.query(KPIDefinition.category, func.count().label("n"))
        .filter(
            KPIDefinition.id.in_(kpi_ids),
            KPIDefinition.is_deleted.is_(False),
            KPIDefinition.category.isnot(None),
        )
        .group_by(KPIDefinition.category)
        .order_by(func.count().desc(), KPIDefinition.category.asc())
        .first()
    )
    return row[0] if row else None


def backfill_categories(db: Session) -> int:
    """Assign a category to every uncategorized dashboard from its widgets' KPIs.

    One-off migration for dashboards created before category auto-assignment.
    Returns the number of dashboards updated.
    """
    updated = 0
    for dashboard in db.query(Dashboard).filter(Dashboard.category.is_(None)).all():
        derived = _dominant_category_from_widgets(db, dashboard.id)
        if derived is not None:
            dashboard.category = derived
            updated += 1
    if updated:
        db.commit()
    return updated


def _dominant_kpi_category(db: Session, connector_id: uuid.UUID) -> str | None:
    """Most common KPI category across a connector's datasets — the DB's data domain.

    Reflects "what kind of data this source holds" (revenue, operational, customer,
    …) from the GenAI-assigned KPI categories. Ties broken alphabetically; returns
    None when the connector has no categorized KPIs.
    """
    row = (
        db.query(KPIDefinition.category, func.count().label("n"))
        .join(Dataset, Dataset.id == KPIDefinition.dataset_id)
        .filter(
            Dataset.connector_id == connector_id,
            Dataset.is_deleted.is_(False),
            KPIDefinition.is_deleted.is_(False),
            KPIDefinition.category.isnot(None),
        )
        .group_by(KPIDefinition.category)
        .order_by(func.count().desc(), KPIDefinition.category.asc())
        .first()
    )
    return row[0] if row else None


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
    db: Session, dashboard_id: uuid.UUID, payload: DashboardUpdate, actor: User
) -> Dashboard:
    dashboard = get_writable_dashboard_or_404(db, dashboard_id, actor)
    updates = payload.model_dump(exclude_unset=True)
    return _with_access(
        dashboard_crud.update_dashboard(db, dashboard, updates), dashboard.my_access
    )


def delete_dashboard(db: Session, dashboard_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    # Deleting stays owner-only — a write grant covers content, not the dashboard itself.
    dashboard = get_owned_dashboard_or_404(db, dashboard_id, owner_id)
    dashboard_crud.delete_dashboard(db, dashboard)


def add_widget(
    db: Session, dashboard_id: uuid.UUID, payload: WidgetCreate, actor: User
) -> DashboardWidget:
    get_writable_dashboard_or_404(db, dashboard_id, actor)
    widget = DashboardWidget(dashboard_id=dashboard_id, **payload.model_dump())
    return dashboard_crud.create_widget(db, widget)


def get_writable_widget_or_404(
    db: Session, dashboard_id: uuid.UUID, widget_id: uuid.UUID, actor: User
) -> DashboardWidget:
    get_writable_dashboard_or_404(db, dashboard_id, actor)
    widget = dashboard_crud.get_widget(db, widget_id)
    if widget is None or widget.dashboard_id != dashboard_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
    return widget


def update_widget(
    db: Session,
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    actor: User,
) -> DashboardWidget:
    widget = get_writable_widget_or_404(db, dashboard_id, widget_id, actor)
    updates = payload.model_dump(exclude_unset=True)
    return dashboard_crud.update_widget(db, widget, updates)


def delete_widget(db: Session, dashboard_id: uuid.UUID, widget_id: uuid.UUID, actor: User) -> None:
    widget = get_writable_widget_or_404(db, dashboard_id, widget_id, actor)
    dashboard_crud.delete_widget(db, widget)


def save_layout(
    db: Session, dashboard_id: uuid.UUID, layout: list[WidgetLayoutUpdate], actor: User
) -> Dashboard:
    dashboard = get_writable_dashboard_or_404(db, dashboard_id, actor)
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


def _permission_response(
    permission: DashboardPermission, grantee: User
) -> DashboardPermissionResponse:
    return DashboardPermissionResponse(
        id=permission.id,
        dashboard_id=permission.dashboard_id,
        user_id=permission.user_id,
        user_email=grantee.email,
        user_name=grantee.name,
        user_role=grantee.role,
        access_level=DashboardAccessLevel(permission.access_level),
        granted_by=permission.granted_by,
        created_at=permission.created_at,
        updated_at=permission.updated_at,
    )


def list_permissions(
    db: Session, dashboard_id: uuid.UUID, actor: User
) -> list[DashboardPermissionResponse]:
    # Managing (and seeing) the sharing panel requires write access.
    get_writable_dashboard_or_404(db, dashboard_id, actor)
    return [
        _permission_response(permission, grantee)
        for permission, grantee in dashboard_crud.list_permissions(db, dashboard_id)
    ]


def grant_permission(
    db: Session,
    dashboard_id: uuid.UUID,
    target_user_id: uuid.UUID,
    access_level: DashboardAccessLevel,
    actor: User,
) -> DashboardPermissionResponse:
    dashboard = get_writable_dashboard_or_404(db, dashboard_id, actor)
    target = user_crud.get_user_by_id(db, target_user_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == dashboard.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The dashboard owner already has full access",
        )
    permission = dashboard_crud.upsert_permission(
        db, dashboard_id, target.id, access_level.value, granted_by=actor.id
    )
    audit_service.record_audit(
        db,
        action="dashboard.permission_granted",
        entity_type="dashboard",
        entity_id=dashboard_id,
        actor_id=actor.id,
        actor_role=actor.role.value,
        summary=f"Granted {access_level.value} access on '{dashboard.name}' to {target.email}",
        details={"user_id": str(target.id), "access_level": access_level.value},
    )
    _publish_permission_change(dashboard_id, target.id, access_level.value)
    return _permission_response(permission, target)


def revoke_permission(
    db: Session, dashboard_id: uuid.UUID, target_user_id: uuid.UUID, actor: User
) -> None:
    dashboard = get_writable_dashboard_or_404(db, dashboard_id, actor)
    permission = dashboard_crud.get_permission(db, dashboard_id, target_user_id)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    target = user_crud.get_user_by_id(db, target_user_id)
    dashboard_crud.delete_permission(db, permission)
    audit_service.record_audit(
        db,
        action="dashboard.permission_revoked",
        entity_type="dashboard",
        entity_id=dashboard_id,
        actor_id=actor.id,
        actor_role=actor.role.value,
        summary=(
            f"Revoked access on '{dashboard.name}' for "
            f"{target.email if target else target_user_id}"
        ),
        details={"user_id": str(target_user_id)},
    )
    _publish_permission_change(dashboard_id, target_user_id, None)
