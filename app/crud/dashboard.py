import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.dashboard import Dashboard, DashboardPermission, DashboardWidget
from app.models.user import User, UserRole


def get_dashboard(db: Session, dashboard_id: uuid.UUID) -> Dashboard | None:
    return (
        db.query(Dashboard)
        .options(selectinload(Dashboard.widgets))
        .filter(Dashboard.id == dashboard_id)
        .first()
    )


def list_dashboards(db: Session, owner_id: uuid.UUID) -> list[Dashboard]:
    return (
        db.query(Dashboard)
        .filter(Dashboard.owner_id == owner_id)
        .order_by(Dashboard.created_at)
        .all()
    )


def list_viewable_dashboards(
    db: Session, viewer_id: uuid.UUID, lower_roles: list[UserRole]
) -> list[Dashboard]:
    """Dashboards the viewer owns, owned by a strictly lower-ranked user, or
    explicitly shared with the viewer via a dashboard permission."""
    granted_ids = db.query(DashboardPermission.dashboard_id).filter(
        DashboardPermission.user_id == viewer_id
    )
    conditions = [Dashboard.owner_id == viewer_id, Dashboard.id.in_(granted_ids)]
    if lower_roles:
        conditions.append(User.role.in_(lower_roles))
    return (
        db.query(Dashboard)
        .join(User, Dashboard.owner_id == User.id)
        .filter(or_(*conditions))
        .order_by(Dashboard.created_at)
        .all()
    )


def create_dashboard(db: Session, dashboard: Dashboard) -> Dashboard:
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)
    return dashboard


def update_dashboard(db: Session, dashboard: Dashboard, updates: dict) -> Dashboard:
    for field, value in updates.items():
        setattr(dashboard, field, value)
    db.commit()
    db.refresh(dashboard)
    return dashboard


def delete_dashboard(db: Session, dashboard: Dashboard) -> None:
    db.delete(dashboard)
    db.commit()


def get_widget(db: Session, widget_id: uuid.UUID) -> DashboardWidget | None:
    return db.get(DashboardWidget, widget_id)


def create_widget(db: Session, widget: DashboardWidget) -> DashboardWidget:
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget


def create_widgets(db: Session, widgets: list[DashboardWidget]) -> list[DashboardWidget]:
    if not widgets:
        return []
    db.add_all(widgets)
    db.commit()
    for widget in widgets:
        db.refresh(widget)
    return widgets


def update_widget(db: Session, widget: DashboardWidget, updates: dict) -> DashboardWidget:
    for field, value in updates.items():
        setattr(widget, field, value)
    db.commit()
    db.refresh(widget)
    return widget


def delete_widget(db: Session, widget: DashboardWidget) -> None:
    db.delete(widget)
    db.commit()


def get_permission(
    db: Session, dashboard_id: uuid.UUID, user_id: uuid.UUID
) -> DashboardPermission | None:
    return (
        db.query(DashboardPermission)
        .filter(
            DashboardPermission.dashboard_id == dashboard_id,
            DashboardPermission.user_id == user_id,
        )
        .first()
    )


def list_permissions(
    db: Session, dashboard_id: uuid.UUID
) -> list[tuple[DashboardPermission, User]]:
    """Grants on a dashboard, joined with the grantee for panel display."""
    return (
        db.query(DashboardPermission, User)
        .join(User, DashboardPermission.user_id == User.id)
        .filter(DashboardPermission.dashboard_id == dashboard_id)
        .order_by(DashboardPermission.created_at)
        .all()
    )


def upsert_permission(
    db: Session,
    dashboard_id: uuid.UUID,
    user_id: uuid.UUID,
    access_level: str,
    granted_by: uuid.UUID,
) -> DashboardPermission:
    permission = get_permission(db, dashboard_id, user_id)
    if permission is None:
        permission = DashboardPermission(
            dashboard_id=dashboard_id,
            user_id=user_id,
            access_level=access_level,
            granted_by=granted_by,
        )
        db.add(permission)
    else:
        permission.access_level = access_level
        permission.granted_by = granted_by
    db.commit()
    db.refresh(permission)
    return permission


def delete_permission(db: Session, permission: DashboardPermission) -> None:
    db.delete(permission)
    db.commit()
