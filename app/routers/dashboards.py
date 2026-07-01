import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardDetailResponse,
    DashboardResponse,
    DashboardUpdate,
    WidgetCreate,
    WidgetLayoutUpdate,
    WidgetResponse,
    WidgetUpdate,
)
from app.services import dashboard_service, insight_service

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


@router.post("", response_model=DashboardResponse, status_code=status.HTTP_201_CREATED)
def create_dashboard(
    payload: DashboardCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard = dashboard_service.create_dashboard(db, payload, owner_id=current_user.id)
    # Kick off a fresh insight-detection pass so the new dashboard surfaces
    # up-to-date KPI insights — scoped to the chosen connector when given.
    background_tasks.add_task(insight_service.run_detection_bg, payload.connector_id)
    return dashboard


@router.get("", response_model=list[DashboardResponse])
def list_dashboards(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.list_dashboards(db, current_user)


@router.get("/{dashboard_id}", response_model=DashboardDetailResponse)
def get_dashboard(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.get_viewable_dashboard_or_404(db, dashboard_id, current_user)


@router.patch("/{dashboard_id}", response_model=DashboardResponse)
def update_dashboard(
    dashboard_id: uuid.UUID,
    payload: DashboardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.update_dashboard(db, dashboard_id, payload, owner_id=current_user.id)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard(
    dashboard_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard_service.delete_dashboard(db, dashboard_id, owner_id=current_user.id)


@router.put("/{dashboard_id}/layout", response_model=DashboardDetailResponse)
def save_layout(
    dashboard_id: uuid.UUID,
    payload: list[WidgetLayoutUpdate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.save_layout(db, dashboard_id, payload, owner_id=current_user.id)


@router.post(
    "/{dashboard_id}/widgets", response_model=WidgetResponse, status_code=status.HTTP_201_CREATED
)
def add_widget(
    dashboard_id: uuid.UUID,
    payload: WidgetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.add_widget(db, dashboard_id, payload, owner_id=current_user.id)


@router.patch("/{dashboard_id}/widgets/{widget_id}", response_model=WidgetResponse)
def update_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    payload: WidgetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return dashboard_service.update_widget(
        db, dashboard_id, widget_id, payload, owner_id=current_user.id
    )


@router.delete("/{dashboard_id}/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_widget(
    dashboard_id: uuid.UUID,
    widget_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    dashboard_service.delete_widget(db, dashboard_id, widget_id, owner_id=current_user.id)
