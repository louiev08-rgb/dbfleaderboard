"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-18

Creates the full schema from the TDS ERD. Hand-authored as the baseline; later
changes should be produced with `alembic revision --autogenerate`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retailers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "forecourts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("retailer_id", sa.Integer, sa.ForeignKey("retailers.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("site_code", sa.String(50), nullable=False),
        sa.Column("timezone", sa.String(50), server_default="Africa/Johannesburg"),
        sa.Column("status", sa.String(20), server_default="active"),
    )
    op.create_table(
        "pumps",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("forecourt_id", sa.Integer, sa.ForeignKey("forecourts.id"), nullable=False, index=True),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("mode", sa.String(10), server_default="fuel"),
        sa.Column("pos_device_id", sa.String(100)),
        sa.Column("webhook_secret", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), server_default="active"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("retailer_id", sa.Integer, sa.ForeignKey("retailers.id"), nullable=True, index=True),
        sa.Column("forecourt_id", sa.Integer, sa.ForeignKey("forecourts.id"), nullable=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("mfa_enabled", sa.Boolean, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("phone", sa.String(30)),
        sa.Column("name", sa.String(200)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("retailer_id", sa.Integer, sa.ForeignKey("retailers.id"), nullable=False, index=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("plate", sa.String(20), nullable=False, index=True),
        sa.Column("nickname", sa.String(100)),
        sa.Column("type", sa.String(10), server_default="fuel"),
        sa.Column("flag", sa.String(10), server_default="ok"),
        sa.Column("wallet_balance", sa.Numeric(12, 2), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("retailer_id", "plate", name="uq_vehicle_plate_per_retailer"),
    )
    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=False, index=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("psp_token", sa.String(255)),
        sa.Column("card_mask", sa.String(30)),
        sa.Column("is_default", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "coupons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id"), nullable=False, index=True),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, nullable=True, index=True),
        sa.Column("method_id", sa.Integer, sa.ForeignKey("payment_methods.id"), nullable=True),
        sa.Column("state", sa.String(20), server_default="created", index=True),
        sa.Column("amount_authorised", sa.Numeric(12, 2), server_default="0"),
        sa.Column("amount_captured", sa.Numeric(12, 2), server_default="0"),
        sa.Column("fee", sa.Numeric(12, 2), server_default="0"),
        sa.Column("net", sa.Numeric(12, 2), server_default="0"),
        sa.Column("currency", sa.String(3), server_default="ZAR"),
        sa.Column("psp_reference", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_captured <= amount_authorised", name="ck_capture_le_auth"),
    )
    op.create_table(
        "charging_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_ref", sa.String(40), unique=True, index=True),
        sa.Column("pump_id", sa.Integer, sa.ForeignKey("pumps.id"), nullable=False, index=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id"), nullable=True),
        sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("operator_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("payment_id", sa.Integer, sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("mode", sa.String(10), server_default="fuel"),
        sa.Column("target", sa.Numeric(12, 3), server_default="0"),
        sa.Column("price_per_unit", sa.Numeric(12, 2), server_default="0"),
        sa.Column("dispensed", sa.Numeric(12, 3), server_default="0"),
        sa.Column("state", sa.String(20), server_default="created"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "transaction_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("charging_sessions.id"), index=True),
        sa.Column("payment_id", sa.Integer, sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("forecourt_id", sa.Integer, sa.ForeignKey("forecourts.id"), index=True),
        sa.Column("plate", sa.String(20)),
        sa.Column("mode", sa.String(10)),
        sa.Column("units", sa.Numeric(12, 3)),
        sa.Column("unit_type", sa.String(5)),
        sa.Column("price_per_unit", sa.Numeric(12, 2)),
        sa.Column("total", sa.Numeric(12, 2)),
        sa.Column("payment_outcome", sa.String(20)),
        sa.Column("ts", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "settlements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("retailer_id", sa.Integer, sa.ForeignKey("retailers.id"), index=True),
        sa.Column("forecourt_id", sa.Integer, sa.ForeignKey("forecourts.id"), index=True),
        sa.Column("period", sa.String(10)),
        sa.Column("gross", sa.Numeric(12, 2), server_default="0"),
        sa.Column("fees", sa.Numeric(12, 2), server_default="0"),
        sa.Column("net", sa.Numeric(12, 2), server_default="0"),
        sa.Column("payout_reference", sa.String(100)),
        sa.Column("status", sa.String(20), server_default="pending"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("retailer_id", sa.Integer, sa.ForeignKey("retailers.id"), nullable=True),
        sa.Column("action", sa.String(80)),
        sa.Column("entity", sa.String(80)),
        sa.Column("entity_id", sa.String(40)),
        sa.Column("detail", sa.Text),
        sa.Column("ip_address", sa.String(50)),
        sa.Column("ts", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("idempotency_key", sa.String(100), unique=True, index=True),
        sa.Column("source", sa.String(20)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    for table in [
        "webhook_events", "audit_logs", "settlements", "transaction_logs",
        "charging_sessions", "payments", "coupons", "payment_methods",
        "vehicles", "customers", "users", "pumps", "forecourts", "retailers",
    ]:
        op.drop_table(table)
