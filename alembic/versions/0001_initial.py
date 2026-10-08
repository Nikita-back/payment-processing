from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed')",
            name="ck_payments_status",
        ),
        sa.CheckConstraint(
            "currency IN ('RUB', 'USD', 'EUR')",
            name="ck_payments_currency",
        ),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_idempotency_key", "payments", ["idempotency_key"], unique=True)
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'published')", name="ck_outbox_status"),
    )
    op.create_index("ix_outbox_aggregate_id", "outbox", ["aggregate_id"])
    op.create_index("ix_outbox_pending_created", "outbox", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_pending_created", table_name="outbox")
    op.drop_index("ix_outbox_aggregate_id", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("ix_payments_idempotency_key", table_name="payments")
    op.drop_table("payments")
