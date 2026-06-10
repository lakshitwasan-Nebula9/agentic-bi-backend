DATABASE STRUCTURE - AGENTIC BI PLATFORM
=========================================

## Sprint 1 Focus

These are the tables to build now. Everything else in this doc is the target full
schema for context, but is out of scope until later sprints.

**tenants**
- id, name, plan, config (JSONB), created_at

**users**
- id, tenant_id, email, hashed_password / auth_provider_id, role (enum: executive |
  business_manager | analyst | operations), created_at, is_active

**connectors**
- id, tenant_id, type (postgres|mysql|rest_api|csv...), name,
  encrypted_credentials (encrypted JSONB), status (active|error|disabled),
  sync_frequency (real-time|hourly|daily|on-demand), created_at, updated_at

**connector_syncs**
- id, connector_id, started_at, completed_at, row_count, error, status
  (running|success|failed)

**datasets**
- id, tenant_id, connector_id, schema_fingerprint (JSONB),
  quality_metrics (JSONB: completeness, consistency, recency, null_rate),
  quality_score, last_synced_at, status (active|quarantined)

### Notes
- All tables carry `tenant_id` (except `tenants` itself) with RLS policies enforced
  at the DB layer.
- `encrypted_credentials` uses app-layer encryption (Fernet/AES); key from secrets
  manager / env.
- Connector audit trail lives in `connector_syncs` — one row per sync attempt,
  including retries and errors.

---

## Recommended Database Structure (Full / Future Schema)

### Schema Organization

Use one PostgreSQL schema with `tenant_id` on every table + Row-Level Security policies. The PRD says logical isolation is the default; physical isolation (separate schemas/instances) is only for Tier-1 enterprise — don't over-engineer it at MVP.


### Table Groups

**1. Identity & Access**

tenants           — id, name, plan, config
users             — id, tenant_id, email, role (enum), auth_provider_id

Role enum: executive | business_manager | analyst | operations


**2. Connector Registry**

connectors        — id, tenant_id, type (postgres|mysql|rest_api|csv...), name,
                    encrypted_credentials (encrypted JSONB), status, sync_frequency
connector_syncs   — id, connector_id, started_at, completed_at, row_count, error, status
datasets          — id, tenant_id, connector_id, schema_fingerprint (JSONB),
                    quality_score, last_synced_at, status (active|quarantined)


**3. KPI Engine**

kpi_definitions   — id, tenant_id, name, formula, chart_type, owner_user_id,
                    status (draft|pending|certified), version, certified_at, certified_by
kpi_versions      — id, kpi_id, version, formula, changed_by, changed_at, reason
kpi_snapshots     — id, kpi_id, tenant_id, computed_at, value, period_start, period_end
                    (append-only, partitioned by month — this is the time-series store)

kpi_snapshots should NEVER have UPDATEs — enforce this at the API layer.


**4. Dashboards**

dashboards        — id, tenant_id, name, type (personal|team|executive),
                    status (draft|pending|published), version, created_by
dashboard_versions— id, dashboard_id, version, layout_config (JSONB), saved_at, saved_by
dashboard_widgets — id, dashboard_id, kpi_id, widget_type, x, y, w, h, config (JSONB)


**5. Approval Queues (HITL)**

approval_requests — id, tenant_id, entity_type (kpi|dashboard|action),
                    entity_id, status (pending|approved|rejected),
                    requester_id, approver_id, requested_at, resolved_at, notes

One generic table handles KPI certification, dashboard sign-off, and P1 action approvals — they all follow the same workflow.


**6. Insight & Action Pipeline**

insights          — id, tenant_id, kpi_id, category (revenue|operational|customer|strategic|financial),
                    severity (p1|p2|p3), confidence_score, detected_at, status,
                    rationale, evidence (JSONB), time_period_delta (JSONB)
actions           — id, tenant_id, insight_id, type, priority,
                    status (pending_approval|approved|executed|rejected),
                    assigned_to_user_id, approved_by, executed_at, channels (JSONB)
tasks             — id, tenant_id, action_id, assignee_id, status
                    (open|in_progress|resolved), due_at, resolved_at, resolution_note


**7. Feedback & Learning**

insight_feedback  — id, tenant_id, insight_id, user_id, signal (accept|reject|comment),
                    comment, created_at
                    (used by Insight Agent to tune thresholds — never deleted)


**8. Audit Log (immutable)**

audit_logs        — id, tenant_id, actor_id, event_type, entity_type, entity_id,
                    payload (JSONB), created_at

Enforce immutability with a Postgres trigger that raises an exception on UPDATE/DELETE.


**9. Vector Store (pgvector)**

embeddings        — id, tenant_id, entity_type (kpi|glossary|stakeholder_map),
                    entity_id, embedding vector(1536), metadata (JSONB)

The pgvector extension adds the vector column type. Index with ivfflat for ANN queries.


### Key Design Decisions

| Decision                | Recommendation                              | Why                                                              |
|-------------------------|---------------------------------------------|------------------------------------------------------------------|
| Tenant isolation        | RLS on all tables with tenant_id            | Matches PRD default; simpler than schema-per-tenant at MVP       |
| KPI time-series         | Postgres partitioned table (by month)       | No TimescaleDB dependency; simpler ops for MVP                   |
| Approval flow           | One generic approval_requests table         | KPI, dashboard, and action approvals are structurally identical  |
| Audit immutability      | Trigger-enforced, no FK cascade deletes     | Postgres doesn't have native immutable tables; trigger is safest |
| Credentials storage     | Encrypted JSONB in connectors               | Encrypted at app layer (Fernet/AES); secret key in env/secrets   |
| Agent events            | Don't persist in Postgres yet               | Redis Streams handles in-flight events; add only if replay needed|


### What to Defer

- reports table (Sprint 5 — Reporting Agent)
- agent_memory / prompt versioning table (can live in pgvector as embeddings)
- scenarios table (Phase 2 — What-If Analysis)
