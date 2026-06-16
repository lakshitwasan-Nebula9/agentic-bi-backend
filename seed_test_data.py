from sqlalchemy import text

from app.core.database import SessionLocal

db = SessionLocal()

db.execute(
    text(
        """
    INSERT INTO data_connectors (id, name, connector_type, host, port, database_name, username, encrypted_password, is_active, created_at, updated_at)
    VALUES ('aaaaaaaa-0000-0000-0000-000000000001', 'test-connector', 'postgres', 'localhost', 5432, 'agentic_bi', 'test_user', 'dummy', true, now(), now())
    ON CONFLICT DO NOTHING
"""
    )
)

db.execute(
    text(
        """
    INSERT INTO datasets (id, connector_id, name, source_query, row_count, status, created_at, updated_at)
    VALUES ('bbbbbbbb-0000-0000-0000-000000000001', 'aaaaaaaa-0000-0000-0000-000000000001', 'orders', 'SELECT * FROM orders', 0, 'active', now(), now())
    ON CONFLICT DO NOTHING
"""
    )
)

db.commit()
db.close()
print("done — connector and dataset inserted")
