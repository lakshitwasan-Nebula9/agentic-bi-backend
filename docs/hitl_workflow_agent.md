# HITL Workflow Agent

Human-in-the-Loop (HITL) orchestration layer that gates KPI certification behind a multi-stage human review before downstream agents (Insight, Reporting) consume the data.

---

## Role in the Pipeline

```
KPI Agent
    └─► kpi_generated (Redis)
            └─► HITLWorkflowAgent
                    ├─► creates ApprovalRequests in DB
                    └─► kpi_pending_review (Redis)
                                └─► Insight / Reporting Agents
```

The HITL agent sits between the KPI Agent and all consumer agents. No KPI reaches the Insight or Reporting agents without passing review.

---

## Approval Stages

Each KPI travels through three sequential stages. The assigned role is enforced — only the correct role can action each stage.

| Stage | Assigned Role | SLA (configurable) |
|---|---|---|
| `analyst_review` | Data/BI Analyst | `HITL_SLA_ANALYST_HOURS` |
| `business_owner_review` | Business Manager | `HITL_SLA_BUSINESS_OWNER_HOURS` |
| `certification_review` | Executive | `HITL_SLA_CERTIFICATION_HOURS` |

SLA defaults live in `app/core/config.py` and can be overridden via environment variables.

---

## Event Flow

| Event | Direction | Description |
|---|---|---|
| `kpi_generated` | consumed | Triggers batch ApprovalRequest creation |
| `kpi_pending_review` | published | Signals downstream agents to wait for review |
| `kpi_approved` | published | KPI advanced to `certification_review` |
| `kpi_certified` | published | KPI fully approved; consumers can proceed |
| `kpi_rejected` | published | KPI rejected at any stage; consumers skip it |
| `approval_overdue` | published | SLA deadline breached; emitted by the router on `GET /approvals?overdue=true` |

---

## Data Model — `ApprovalRequest`

Stored in the `approval_requests` table. Key fields:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `entity_type` | string | `"kpi"` or `"dashboard"` |
| `entity_id` | UUID | The KPI being reviewed |
| `current_stage` | string | One of the three stages above |
| `status` | string | `pending` → `approved` or `rejected` |
| `assigned_role` | string | Role that must action this stage |
| `sla_deadline` | datetime (tz-aware) | Computed from stage SLA hours |
| `resolved_by` | UUID | Actor who closed the request |
| `resolution_note` | text | Optional note or rejection reason |

Creation is idempotent — if a pending ApprovalRequest already exists for a KPI, `create_kpi_approval` returns the existing one.

---

## API Endpoints

All routes are prefixed `/api/v1`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/approvals/seed` | Manually create ApprovalRequests (use when agent is not running) |
| `GET` | `/approvals` | List approvals; filter by `status`, `entity_type`, `assigned_role`, `overdue` |
| `GET` | `/approvals/{ar_id}` | Get a single ApprovalRequest |
| `POST` | `/approvals/{ar_id}/approve` | Advance stage or certify KPI on final stage |
| `POST` | `/approvals/{ar_id}/reject` | Reject KPI at any stage |

The router publishes the resulting Redis event after each approve/reject action.

---

## Service Layer

`app/services/hitl_workflow_service.py` contains pure business logic with no Redis calls — all event publishing is the caller's responsibility. This keeps service functions unit-testable in isolation.

Key functions:

- **`create_kpi_approval`** — idempotent ApprovalRequest creation with SLA deadline
- **`process_approval`** — advances to the next stage or certifies the KPI on the final stage
- **`process_rejection`** — closes the request and marks the KPI as rejected at any stage
- **`get_overdue_approvals`** — returns all pending requests past their SLA deadline

---

## Running the Agent

```bash
# Standalone worker (subscribes to Redis Streams)
python -m app.agents.hitl_workflow_agent

# Manual seed (when agent is not running)
POST /api/v1/approvals/seed
{"dataset_id": "<uuid>"}
```

The agent uses consumer group `hitl-agent` on Redis Streams, so multiple worker instances can run without duplicate processing.
