import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crud import dashboard as dashboard_crud
from app.models.dashboard import Dashboard, DashboardWidget
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardUpdate,
    WidgetCreate,
    WidgetLayoutUpdate,
    WidgetUpdate,
)


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
    dashboard = Dashboard(name=payload.name, is_default=payload.is_default, owner_id=owner_id)
    return dashboard_crud.create_dashboard(db, dashboard)


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
