from sqlalchemy.orm import Session

from app.models.org_settings import OrgSettings


def create_org_settings(db: Session, org_settings: OrgSettings) -> OrgSettings:
    db.add(org_settings)
    return org_settings
