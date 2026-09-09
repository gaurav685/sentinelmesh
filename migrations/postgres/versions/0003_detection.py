"""Phase-5 detection schema: detection, anomaly, threat_score, security_alert.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-09

Notes
-----
- System of record for `detection-engine` (`docs/architecture/service-catalog.md`).
  `api-gateway` builds a read projection from the `detections` Kafka topic; it
  does not write here.
- Enum columns are `varchar` + `CHECK` (values mirror `sm_contracts` enums).
- `updated_at` is trigger-maintained (`sm_set_updated_at()` from migration 0001).
- No performance or accuracy claim is encoded anywhere. A `detection` row's
  meaning is its `evidence` JSON (Constitution §3).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEVERITY = "'info', 'low', 'medium', 'high', 'critical'"
_DETECTOR = "'rule', 'statistical', 'isolation_forest', 'autoencoder', 'composite'"
_ANOMALY_METHOD = "'mad_zscore', 'rolling_quantile', 'isolation_forest', 'autoencoder'"
_SCORING_STATUS = "'ok', 'degraded'"
_DETECTION_STATUS = "'new', 'triaged', 'confirmed', 'dismissed', 'suppressed'"
_ALERT_STATUS = "'open', 'acknowledged', 'closed'"
_SUBJECT_TYPE = "'identity', 'host', 'ip', 'domain', 'detection'"

_TIMESTAMP_TABLES = ("detection", "anomaly", "threat_score", "security_alert")

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def _ts_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    # ---- detection -------------------------------------------------------
    op.create_table(
        "detection",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detector", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("scoring_status", sa.String(length=16), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'new'")),
        sa.Column("entities", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("technique_ids", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("raw_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_detection"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_detection_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"detector IN ({_DETECTOR})", name="ck_detection_detector"),
        sa.CheckConstraint(f"severity IN ({_SEVERITY})", name="ck_detection_severity"),
        sa.CheckConstraint(f"scoring_status IN ({_SCORING_STATUS})", name="ck_detection_scoring_status"),
        sa.CheckConstraint(f"status IN ({_DETECTION_STATUS})", name="ck_detection_status"),
        sa.CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_detection_score_range"),
    )
    op.create_index("ix_detection_tenant_id", "detection", ["tenant_id"])
    op.execute("CREATE INDEX ix_detection_tenant_id_created_at ON detection (tenant_id, created_at DESC)")
    op.create_index(
        "ix_detection_tenant_id_severity_status", "detection", ["tenant_id", "severity", "status"]
    )
    op.create_index("ix_detection_tenant_id_dedup_key", "detection", ["tenant_id", "dedup_key"])

    # ---- anomaly ------------------------------------------------------
    op.create_table(
        "anomaly",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("feature_schema_version", sa.String(length=32), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("normalized_score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column("entity", _JSONB, nullable=True),
        sa.Column("raw_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("features", _JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_anomaly"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_anomaly_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"method IN ({_ANOMALY_METHOD})", name="ck_anomaly_method"),
        sa.CheckConstraint(
            "normalized_score >= 0.0 AND normalized_score <= 1.0", name="ck_anomaly_normalized_score_range"
        ),
    )
    op.create_index("ix_anomaly_tenant_id", "anomaly", ["tenant_id"])
    op.execute("CREATE INDEX ix_anomaly_tenant_id_observed_at ON anomaly (tenant_id, observed_at DESC)")
    op.create_index("ix_anomaly_tenant_id_is_anomaly", "anomaly", ["tenant_id", "is_anomaly"])

    # ---- threat_score -----------------------------------------------
    op.create_table(
        "threat_score",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("components", _JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("weights_version", sa.String(length=32), nullable=False),
        sa.Column("scoring_status", sa.String(length=16), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_threat_score"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_threat_score_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"subject_type IN ({_SUBJECT_TYPE})", name="ck_threat_score_subject_type"),
        sa.CheckConstraint(f"scoring_status IN ({_SCORING_STATUS})", name="ck_threat_score_scoring_status"),
        sa.CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_threat_score_score_range"),
        sa.UniqueConstraint("tenant_id", "subject_type", "subject_id", name="uq_threat_score_subject"),
    )
    op.create_index("ix_threat_score_tenant_id", "threat_score", ["tenant_id"])
    op.execute("CREATE INDEX ix_threat_score_tenant_id_score ON threat_score (tenant_id, score DESC)")

    # ---- security_alert --------------------------------------------
    op.create_table(
        "security_alert",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default=sa.text("'open'")),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id", name="pk_security_alert"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenant.id"], name="fk_security_alert_tenant_id_tenant", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["detection_id"], ["detection.id"],
            name="fk_security_alert_detection_id_detection", ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"severity IN ({_SEVERITY})", name="ck_security_alert_severity"),
        sa.CheckConstraint(f"status IN ({_ALERT_STATUS})", name="ck_security_alert_status"),
        sa.UniqueConstraint("detection_id", name="uq_security_alert_detection_id"),
    )
    op.create_index("ix_security_alert_tenant_id", "security_alert", ["tenant_id"])
    op.execute(
        "CREATE INDEX ix_security_alert_tenant_id_status_opened_at "
        "ON security_alert (tenant_id, status, opened_at DESC)"
    )

    # ---- updated_at triggers ---------------------------------------
    for table in _TIMESTAMP_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_set_updated_at
            BEFORE UPDATE ON "{table}"
            FOR EACH ROW EXECUTE FUNCTION sm_set_updated_at();
            """
        )


def downgrade() -> None:
    for table in _TIMESTAMP_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table}_set_updated_at ON "{table}"')
    op.drop_table("security_alert")
    op.drop_table("threat_score")
    op.drop_table("anomaly")
    op.drop_table("detection")
