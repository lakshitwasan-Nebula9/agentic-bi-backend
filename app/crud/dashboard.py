import uuid

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.dashboard import Dashboard, DashboardWidget
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
    """Dashboards the viewer owns, plus any owned by a strictly lower-ranked user."""
    conditions = [Dashboard.owner_id == viewer_id]
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
