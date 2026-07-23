"""Add tenant, factory, device authorization, Agent ownership and traces."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0003_enterprise_scope"
down_revision = "0002_daily_summaries"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_FACTORY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])
    op.create_table(
        "factories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_factory_tenant_code"),
    )
    op.create_index("ix_factories_tenant_id", "factories", ["tenant_id"])
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, slug, name, is_active, created_at) "
            "VALUES (:id, 'default', '默认租户', true, CURRENT_TIMESTAMP)"
        ).bindparams(id=DEFAULT_TENANT_ID)
    )
    op.execute(
        sa.text(
            "INSERT INTO factories (id, tenant_id, code, name, is_active, created_at) "
            "VALUES (:id, :tenant_id, 'DEFAULT', '默认工厂', true, CURRENT_TIMESTAMP)"
        ).bindparams(id=DEFAULT_FACTORY_ID, tenant_id=DEFAULT_TENANT_ID)
    )

    scoped_tables = ("users", "control_plans", "audit_events", "daily_summaries", "knowledge_documents")
    for table in scoped_tables:
        op.add_column(
            table,
            sa.Column(
                "tenant_id",
                sa.Uuid(),
                nullable=False,
                server_default=str(DEFAULT_TENANT_ID),
            ),
        )
        op.create_foreign_key(
            f"fk_{table}_tenant_id",
            table,
            "tenants",
            ["tenant_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    for table in ("control_plans", "daily_summaries", "knowledge_documents"):
        op.add_column(
            table,
            sa.Column(
                "factory_id",
                sa.Uuid(),
                nullable=False,
                server_default=str(DEFAULT_FACTORY_ID),
            ),
        )
        op.create_foreign_key(
            f"fk_{table}_factory_id",
            table,
            "factories",
            ["factory_id"],
            ["id"],
        )
        op.create_index(f"ix_{table}_factory_id", table, ["factory_id"])

    op.add_column("audit_events", sa.Column("factory_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_audit_events_factory_id",
        "audit_events",
        "factories",
        ["factory_id"],
        ["id"],
    )
    op.create_index("ix_audit_events_factory_id", "audit_events", ["factory_id"])
    op.add_column(
        "daily_summaries",
        sa.Column("insight_payload", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "user_factory_access",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("factory_id", sa.Uuid(), sa.ForeignKey("factories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("can_manage_devices", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO user_factory_access (user_id, factory_id, can_manage_devices, created_at) "
            "SELECT id, :factory_id, true, CURRENT_TIMESTAMP FROM users"
        ).bindparams(factory_id=DEFAULT_FACTORY_ID)
    )
    op.create_table(
        "factory_devices",
        sa.Column("device_id", sa.String(128), primary_key=True),
        sa.Column("factory_id", sa.Uuid(), sa.ForeignKey("factories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_name", sa.String(255), nullable=False),
        sa.Column("device_type", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_factory_devices_factory_id", "factory_devices", ["factory_id"])
    op.create_table(
        "agent_threads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("factory_id", sa.Uuid(), sa.ForeignKey("factories.id"), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checkpoint_ns", sa.String(128), nullable=False),
        sa.Column("client_thread_id", sa.String(128), nullable=False),
        sa.Column("checkpoint_thread_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("checkpoint_ns", "client_thread_id", name="uq_agent_thread_client"),
        sa.UniqueConstraint("checkpoint_thread_id"),
    )
    op.create_index("ix_agent_threads_tenant_id", "agent_threads", ["tenant_id"])
    op.create_index("ix_agent_threads_factory_id", "agent_threads", ["factory_id"])
    op.create_index("ix_agent_threads_owner_user_id", "agent_threads", ["owner_user_id"])
    op.create_table(
        "agent_traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("factory_id", sa.Uuid(), sa.ForeignKey("factories.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("thread_id", sa.String(128), nullable=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("route", sa.String(64), nullable=True),
        sa.Column("intent", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("node_timings", sa.JSON(), nullable=False),
        sa.Column("tool_names", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trace_id"),
    )
    for column in ("trace_id", "request_id", "tenant_id", "factory_id", "operation", "status"):
        op.create_index(f"ix_agent_traces_{column}", "agent_traces", [column])


def downgrade() -> None:
    op.drop_table("agent_traces")
    op.drop_table("agent_threads")
    op.drop_table("factory_devices")
    op.drop_table("user_factory_access")
    op.drop_column("daily_summaries", "insight_payload")
    op.drop_index("ix_audit_events_factory_id", table_name="audit_events")
    op.drop_constraint("fk_audit_events_factory_id", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "factory_id")
    for table in ("control_plans", "daily_summaries", "knowledge_documents"):
        op.drop_index(f"ix_{table}_factory_id", table_name=table)
        op.drop_constraint(f"fk_{table}_factory_id", table, type_="foreignkey")
        op.drop_column(table, "factory_id")
    for table in ("users", "control_plans", "audit_events", "daily_summaries", "knowledge_documents"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_constraint(f"fk_{table}_tenant_id", table, type_="foreignkey")
        op.drop_column(table, "tenant_id")
    op.drop_table("factories")
    op.drop_table("tenants")
