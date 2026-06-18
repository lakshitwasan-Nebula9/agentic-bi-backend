"""One-off seed script — inserts 30 dummy order rows into dataset_records."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uuid

from app.core.database import SessionLocal
from app.models.dataset import DatasetRecord

DATASET_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

ORDERS = [
    {
        "order_id": 1,
        "customer_id": 1,
        "total_amount": 320.50,
        "discount_amount": 15.00,
        "item_count": 3,
    },
    {"order_id": 2, "customer_id": 2, "total_amount": 89.99, "discount_amount": 0, "item_count": 1},
    {
        "order_id": 3,
        "customer_id": 3,
        "total_amount": 450.00,
        "discount_amount": 45.00,
        "item_count": 5,
    },
    {
        "order_id": 4,
        "customer_id": 1,
        "total_amount": 175.25,
        "discount_amount": 10.00,
        "item_count": 2,
    },
    {
        "order_id": 5,
        "customer_id": 4,
        "total_amount": 530.00,
        "discount_amount": 53.00,
        "item_count": 4,
    },
    {
        "order_id": 6,
        "customer_id": 5,
        "total_amount": 210.75,
        "discount_amount": 0,
        "item_count": 2,
    },
    {
        "order_id": 7,
        "customer_id": 2,
        "total_amount": 99.00,
        "discount_amount": 5.00,
        "item_count": 1,
    },
    {
        "order_id": 8,
        "customer_id": 6,
        "total_amount": 640.00,
        "discount_amount": 64.00,
        "item_count": 6,
    },
    {
        "order_id": 9,
        "customer_id": 3,
        "total_amount": 385.50,
        "discount_amount": 20.00,
        "item_count": 4,
    },
    {
        "order_id": 10,
        "customer_id": 7,
        "total_amount": 120.00,
        "discount_amount": 0,
        "item_count": 1,
    },
    {
        "order_id": 11,
        "customer_id": 8,
        "total_amount": 275.00,
        "discount_amount": 25.00,
        "item_count": 3,
    },
    {
        "order_id": 12,
        "customer_id": 4,
        "total_amount": 490.99,
        "discount_amount": 30.00,
        "item_count": 5,
    },
    {
        "order_id": 13,
        "customer_id": 9,
        "total_amount": 60.00,
        "discount_amount": 0,
        "item_count": 1,
    },
    {
        "order_id": 14,
        "customer_id": 1,
        "total_amount": 730.00,
        "discount_amount": 73.00,
        "item_count": 7,
    },
    {
        "order_id": 15,
        "customer_id": 5,
        "total_amount": 155.50,
        "discount_amount": 10.00,
        "item_count": 2,
    },
    {
        "order_id": 16,
        "customer_id": 10,
        "total_amount": 880.00,
        "discount_amount": 88.00,
        "item_count": 8,
    },
    {
        "order_id": 17,
        "customer_id": 6,
        "total_amount": 340.25,
        "discount_amount": 0,
        "item_count": 3,
    },
    {
        "order_id": 18,
        "customer_id": 2,
        "total_amount": 195.00,
        "discount_amount": 15.00,
        "item_count": 2,
    },
    {
        "order_id": 19,
        "customer_id": 7,
        "total_amount": 415.75,
        "discount_amount": 40.00,
        "item_count": 4,
    },
    {
        "order_id": 20,
        "customer_id": 8,
        "total_amount": 50.00,
        "discount_amount": 0,
        "item_count": 1,
    },
    {
        "order_id": 21,
        "customer_id": 3,
        "total_amount": 560.00,
        "discount_amount": 56.00,
        "item_count": 5,
    },
    {
        "order_id": 22,
        "customer_id": 9,
        "total_amount": 230.50,
        "discount_amount": 0,
        "item_count": 2,
    },
    {
        "order_id": 23,
        "customer_id": 1,
        "total_amount": 670.00,
        "discount_amount": 67.00,
        "item_count": 6,
    },
    {
        "order_id": 24,
        "customer_id": 4,
        "total_amount": 145.99,
        "discount_amount": 5.00,
        "item_count": 1,
    },
    {
        "order_id": 25,
        "customer_id": 10,
        "total_amount": 390.00,
        "discount_amount": 20.00,
        "item_count": 3,
    },
    {
        "order_id": 26,
        "customer_id": 5,
        "total_amount": 720.50,
        "discount_amount": 72.00,
        "item_count": 7,
    },
    {
        "order_id": 27,
        "customer_id": 6,
        "total_amount": 310.00,
        "discount_amount": 0,
        "item_count": 3,
    },
    {
        "order_id": 28,
        "customer_id": 2,
        "total_amount": 480.25,
        "discount_amount": 48.00,
        "item_count": 4,
    },
    {
        "order_id": 29,
        "customer_id": 7,
        "total_amount": 95.00,
        "discount_amount": 0,
        "item_count": 1,
    },
    {
        "order_id": 30,
        "customer_id": 9,
        "total_amount": 850.00,
        "discount_amount": 85.00,
        "item_count": 8,
    },
]

db = SessionLocal()
try:
    records = [DatasetRecord(dataset_id=DATASET_ID, row_data=row) for row in ORDERS]
    db.add_all(records)
    db.commit()
    print(f"Inserted {len(records)} rows into dataset_records.")
finally:
    db.close()
