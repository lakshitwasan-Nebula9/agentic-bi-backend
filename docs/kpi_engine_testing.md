# KPI Engine — Manual Testing Guide

## Prerequisites

- Postgres running and `DATABASE_URL` set in `.env`
- `GEMINI_API_KEY` set in `.env`
- Migrations applied: `alembic upgrade head`
- venv activated: `source venv/bin/activate` (Mac/Linux) or `venv\Scripts\activate` (Windows)

---

## Step 1 — Seed test data

Only needed once. Creates a dummy connector and dataset row.

```powershell
python seed_test_data.py
```

This inserts:
- Connector ID: `aaaaaaaa-0000-0000-0000-000000000001`
- Dataset ID: `bbbbbbbb-0000-0000-0000-000000000001` (name = `orders`)

---

## Step 2 — Start the server

```powershell
uvicorn app.main:app --reload
```

Swagger UI available at: `http://localhost:8000/docs`

---

## Step 3 — Detect schema

`POST /api/v1/schema/detect`

This annotates the table columns and writes a `schema_metadata` row — required before KPI generation.

```json
{
  "table_name": "orders",
  "columns": [
    {"name": "order_id", "type": "uuid"},
    {"name": "customer_id", "type": "uuid"},
    {"name": "status", "type": "varchar"},
    {"name": "total_amount", "type": "numeric"},
    {"name": "discount_amount", "type": "numeric"},
    {"name": "item_count", "type": "integer"},
    {"name": "created_at", "type": "timestamp"},
    {"name": "shipped_at", "type": "timestamp"}
  ]
}
```

Expected response includes `schema_metadata_id` and `embedding_id`.

---

## Step 4 — Generate KPIs

`POST /api/v1/datasets/bbbbbbbb-0000-0000-0000-000000000001/kpis/generate`

No request body. Gemini generates 3–6 KPI definitions from the schema metadata.

Expected response: list of KPI UUIDs, e.g.
```json
["48cccd9e-...", "669b169f-...", "322c6a82-..."]
```

---

## Step 5 — View the approval queue

`GET /api/v1/kpis?status=pending_review`

Returns all generated KPIs waiting for analyst review. Each KPI has:
- `name`, `display_name`, `description`, `category`
- `formula` (human-readable)
- `sql_expression` (executable SQL fragment)
- `direction`, `unit`, `suggested_chart`
- `status = "pending_review"`

---

## Step 6 — View a single KPI

`GET /api/v1/kpis/{kpi_id}`

---

## Step 7 — Edit a KPI (analyst)

`PUT /api/v1/kpis/{kpi_id}`

```json
{
  "display_name": "Total Revenue",
  "owner_name": "Aanchal",
  "owner_role": "analyst"
}
```

Only include fields you want to change. Bumps the version and writes an audit row to `kpi_versions`.

---

## Step 8 — Check the approval queue

`GET /api/v1/approvals?entity_type=kpi&status=pending`

Returns one `ApprovalRequest` per generated KPI. Grab an `id` — you'll use it as `{ar_id}` in steps 9–11.

```json
{
  "id": "<ar_id>",
  "entity_type": "kpi",
  "current_stage": "analyst_review",
  "assigned_role": "analyst",
  "status": "pending",
  "is_overdue": false
}
```

---

## Step 9 — Analyst approves (stage 1 → 2)

`POST /api/v1/approvals/{ar_id}/approve`

```json
{
  "actor_id": "bbbbbbbb-0000-0000-0000-000000000001",
  "actor_role": "analyst",
  "note": null
}
```

AR advances to `current_stage = business_owner_review`. No event published yet.

Wrong role test: use `"actor_role": "executive"` → expect `403`.

---

## Step 10 — Business owner approves (stage 2 → 3)

`POST /api/v1/approvals/{ar_id}/approve`

```json
{
  "actor_id": "bbbbbbbb-0000-0000-0000-000000000001",
  "actor_role": "business_owner",
  "note": null
}
```

AR advances to `current_stage = certification_review`. `kpi_approved` event published.

---

## Step 11 — Certifier approves (final stage — certifies KPI)

`POST /api/v1/approvals/{ar_id}/approve`

```json
{
  "actor_id": "bbbbbbbb-0000-0000-0000-000000000001",
  "actor_role": "executive",
  "note": null
}
```

AR `status` → `approved`, `resolved_at` set. KPI `status` → `certified`. `kpi_certified` event published.

Verify: `GET /api/v1/kpis/{kpi_id}` → `"status": "certified"`.

---

## Step 12 — Reject a KPI (any stage)

`POST /api/v1/approvals/{ar_id}/reject`

```json
{
  "actor_id": "bbbbbbbb-0000-0000-0000-000000000001",
  "actor_role": "analyst",
  "rejection_reason": "SQL expression is incorrect for this dataset"
}
```

Use the `actor_role` matching the current stage (`analyst`, `business_owner`, or `executive`). AR `status` → `rejected`, KPI `status` → `rejected`. `kpi_rejected` event published.

---

## Step 13 — View snapshots (computed values)

`GET /api/v1/kpis/{kpi_id}/snapshots`

Returns time-series snapshot rows. Each snapshot has the computed `value` from when the KPI was generated (or recomputed).

---

## Step 14 — Recompute a snapshot

`POST /api/v1/kpis/{kpi_id}/recompute`

No body. Re-executes the KPI's SQL against `dataset_records` and writes a new snapshot. Use this after a dataset refresh.

---

## Step 15 — Filter KPIs by dataset or status

```
GET /api/v1/kpis?dataset_id=bbbbbbbb-0000-0000-0000-000000000001
GET /api/v1/kpis?status=certified
GET /api/v1/kpis?dataset_id=bbbbbbbb-0000-0000-0000-000000000001&status=pending_review
```

---

## KPI Lifecycle

```
draft → pending_review ──────────────────────→ certified
              ↓ (ApprovalRequest drives this)       ↑
         analyst_review                             │
              ↓                               certification_review (executive approves)
         business_owner_review                      │
              ↓ kpi_approved published ─────────────┘
              ↓
         rejected (any stage)
```

KPI status stays `pending_review` through all three approval stages. It only flips to `certified` or `rejected` when the ApprovalRequest is closed.

All state transitions are append-only — every change is recorded in `kpi_versions`.

---

## Run unit tests

```powershell
pytest tests/test_kpi_agent.py -v
```

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| 404 on `/kpis/generate` | Dataset not in DB | Run `seed_test_data.py` |
| 404 on `/kpis/generate` | Schema not detected yet | Run Step 3 first |
| 503 on `/kpis/generate` | Missing Gemini key | Set `GEMINI_API_KEY` in `.env` |
| 409 on certify/reject | Invalid state transition | Check current `status` with `GET /kpis/{id}` |
| 422 on recompute | LLM wrote invalid SQL | Reject the KPI, regenerate |
