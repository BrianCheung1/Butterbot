from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    pass


def _sqlite_check(expression: str, name: str) -> CheckConstraint:
    return CheckConstraint(expression, name=name).ddl_if(dialect="sqlite")


def _sqlite_uuid(column: str, *, nullable: bool = False) -> CheckConstraint:
    valid = (
        f"typeof({column}) = 'text' AND length({column}) = 32 "
        f"AND {column} = lower({column}) AND {column} NOT GLOB '*[^0-9a-f]*'"
    )
    if nullable:
        valid = f"{column} IS NULL OR ({valid})"
    return _sqlite_check(valid, f"ck_sqlite_{column}_uuid")


def _sqlite_integer(column: str, *, nullable: bool = False) -> CheckConstraint:
    valid = f"typeof({column}) = 'integer'"
    if nullable:
        valid = f"{column} IS NULL OR {valid}"
    return _sqlite_check(valid, f"ck_sqlite_{column}_integer")


def _sqlite_reference(
    column: str,
    name: str,
    *,
    maximum: int = 255,
    nullable: bool = False,
) -> CheckConstraint:
    valid = (
        f"length({column}) BETWEEN 1 AND {maximum} "
        f"AND instr({column}, char(0)) = 0 "
        f"AND {column} NOT GLOB '*[^!-~]*'"
    )
    if nullable:
        valid = f"{column} IS NULL OR ({valid})"
    return _sqlite_check(valid, name)


class PlayerModel(Base):
    __tablename__ = "players"
    __table_args__ = (
        CheckConstraint("discord_user_id >= 0", name="ck_players_discord_user_id_nonnegative"),
        CheckConstraint(
            "lifecycle_state IN ('active', 'pseudonymized')",
            name="ck_players_lifecycle_state",
        ),
        _sqlite_uuid("id"),
        _sqlite_integer("discord_user_id"),
        _sqlite_integer("created_at_ms"),
        UniqueConstraint("discord_user_id", name="uq_players_discord_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    lifecycle_state: Mapped[str] = mapped_column(String(24))


class TransportRequestModel(Base):
    __tablename__ = "operations_transport_requests"
    __table_args__ = (
        CheckConstraint(
            "length(namespace) BETWEEN 3 AND 100 "
            "AND instr(namespace, char(0)) = 0 "
            "AND namespace = lower(namespace) "
            "AND namespace GLOB '[a-z]*.[a-z]*' "
            "AND namespace NOT GLOB '*[^a-z0-9_.]*' "
            "AND namespace NOT GLOB '*.[^a-z]*' "
            "AND namespace NOT LIKE '%..%' "
            "AND namespace NOT LIKE '%.'",
            name="ck_operations_transport_requests_namespace_length",
        ),
        CheckConstraint(
            "length(transport_key) BETWEEN 1 AND 255 AND instr(transport_key, char(0)) = 0",
            name="ck_operations_transport_requests_key_length",
        ),
        CheckConstraint(
            "length(actor_kind) BETWEEN 1 AND 32 "
            "AND instr(actor_kind, char(0)) = 0 "
            "AND actor_kind = lower(actor_kind) "
            "AND actor_kind GLOB '[a-z]*' "
            "AND actor_kind NOT GLOB '*[^a-z0-9_.]*' "
            "AND actor_kind NOT GLOB '*.[^a-z]*' "
            "AND actor_kind NOT LIKE '%..%' "
            "AND actor_kind NOT LIKE '%.'",
            name="ck_operations_transport_requests_actor_kind_length",
        ),
        _sqlite_reference(
            "actor_reference",
            "ck_operations_transport_requests_actor_reference_length",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64 "
            "AND instr(request_fingerprint, char(0)) = 0 "
            "AND request_fingerprint = lower(request_fingerprint) "
            "AND request_fingerprint NOT GLOB '*[^0-9a-f]*'",
            name="ck_operations_transport_requests_fingerprint_length",
        ),
        CheckConstraint(
            "outcome_code IS NULL OR ("
            "length(outcome_code) BETWEEN 1 AND 100 "
            "AND instr(outcome_code, char(0)) = 0 "
            "AND outcome_code = lower(outcome_code) "
            "AND outcome_code GLOB '[a-z]*' "
            "AND outcome_code NOT GLOB '*[^a-z0-9_.]*' "
            "AND outcome_code NOT GLOB '*.[^a-z]*' "
            "AND outcome_code NOT LIKE '%..%' "
            "AND outcome_code NOT LIKE '%.')",
            name="ck_operations_transport_requests_outcome_code_length",
        ),
        CheckConstraint(
            "(outcome_kind IS NULL AND outcome_code IS NULL AND outcome_payload IS NULL "
            "AND completed_at_ms IS NULL AND retain_until_ms IS NULL) OR "
            "(outcome_kind IN ('success', 'typed_rejection') AND outcome_code IS NOT NULL "
            "AND outcome_payload IS NOT NULL AND completed_at_ms IS NOT NULL "
            "AND retain_until_ms > completed_at_ms)",
            name="ck_operations_transport_requests_completion",
        ),
        _sqlite_check(
            "outcome_payload IS NULL OR CASE WHEN json_valid(outcome_payload) "
            "THEN json_type(outcome_payload) = 'object' ELSE 0 END",
            "ck_operations_transport_requests_outcome_payload_json_object",
        ),
        _sqlite_uuid("id"),
        _sqlite_integer("completed_at_ms", nullable=True),
        _sqlite_integer("retain_until_ms", nullable=True),
        UniqueConstraint(
            "namespace",
            "transport_key",
            name="uq_operations_transport_requests_namespace_key",
        ),
        Index("ix_operations_transport_requests_retain_until", "retain_until_ms"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(100))
    transport_key: Mapped[str] = mapped_column(String(255))
    actor_kind: Mapped[str] = mapped_column(String(32))
    actor_reference: Mapped[str] = mapped_column(String(255))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    outcome_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    outcome_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    outcome_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    retain_until_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AccountModel(Base):
    __tablename__ = "economy_accounts"
    __table_args__ = (
        CheckConstraint("currency_key = 'coin'", name="ck_economy_accounts_currency"),
        CheckConstraint(
            "(account_kind = 'wallet' AND player_id IS NOT NULL AND system_key IS NULL) OR "
            "(account_kind IN ('issuance', 'retirement') AND player_id IS NULL "
            "AND system_key IS NOT NULL)",
            name="ck_economy_accounts_owner_kind",
        ),
        _sqlite_check(
            "system_key IS NULL OR (length(system_key) BETWEEN 3 AND 100 "
            "AND instr(system_key, char(0)) = 0 AND system_key = lower(system_key) "
            "AND system_key GLOB '[a-z]*.[a-z]*' "
            "AND system_key NOT GLOB '*[^a-z0-9_.]*' "
            "AND system_key NOT GLOB '*.[^a-z]*' "
            "AND system_key NOT LIKE '%..%' AND system_key NOT LIKE '%.')",
            "ck_economy_accounts_system_key",
        ),
        _sqlite_uuid("id"),
        _sqlite_uuid("player_id", nullable=True),
        _sqlite_integer("created_at_ms"),
        UniqueConstraint("id", "account_kind", name="uq_economy_accounts_id_kind"),
        UniqueConstraint("player_id", "account_kind", name="uq_economy_accounts_player_kind"),
        UniqueConstraint("system_key", name="uq_economy_accounts_system_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    player_id: Mapped[UUID | None] = mapped_column(
        Uuid(), ForeignKey("players.id", ondelete="RESTRICT"), nullable=True
    )
    account_kind: Mapped[str] = mapped_column(String(24))
    currency_key: Mapped[str] = mapped_column(String(32))
    system_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)


class AccountBalanceModel(Base):
    __tablename__ = "economy_account_balances"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_economy_account_balances_version"),
        CheckConstraint(
            "(account_kind = 'wallet' AND amount >= 0) OR "
            "(account_kind = 'issuance' AND amount <= 0) OR "
            "(account_kind = 'retirement' AND amount >= 0)",
            name="ck_economy_account_balances_polarity",
        ),
        _sqlite_uuid("account_id"),
        _sqlite_integer("amount"),
        _sqlite_integer("version"),
        ForeignKeyConstraint(
            ["account_id", "account_kind"],
            ["economy_accounts.id", "economy_accounts.account_kind"],
            name="fk_economy_account_balances_account",
            ondelete="RESTRICT",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    account_kind: Mapped[str] = mapped_column(String(24))
    amount: Mapped[int] = mapped_column(BigInteger)
    version: Mapped[int] = mapped_column(BigInteger)


class IntegrityViolationModel(Base):
    __tablename__ = "operations_integrity_violations"
    __table_args__ = (
        CheckConstraint(
            "violation_kind IN ('account_without_balance', 'player_without_wallet')",
            name="ck_operations_integrity_violations_kind",
        ),
        _sqlite_uuid("aggregate_id"),
        Index("ix_operations_integrity_violations_aggregate_id", "aggregate_id"),
    )

    violation_kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)


class LedgerTransactionModel(Base):
    __tablename__ = "economy_ledger_transactions"
    __table_args__ = (
        CheckConstraint(
            "discord_interaction_id IS NULL OR discord_interaction_id >= 0",
            name="ck_economy_ledger_transactions_interaction_nonnegative",
        ),
        _sqlite_check(
            "length(transaction_kind) BETWEEN 1 AND 64 "
            "AND instr(transaction_kind, char(0)) = 0 "
            "AND transaction_kind = lower(transaction_kind) "
            "AND transaction_kind GLOB '[a-z]*' "
            "AND transaction_kind NOT GLOB '*[^a-z0-9_.]*' "
            "AND transaction_kind NOT GLOB '*.[^a-z]*' "
            "AND transaction_kind NOT LIKE '%..%' AND transaction_kind NOT LIKE '%.'",
            "ck_economy_ledger_transactions_kind",
        ),
        _sqlite_check(
            "length(actor_kind) BETWEEN 1 AND 32 AND instr(actor_kind, char(0)) = 0 "
            "AND actor_kind = lower(actor_kind) AND actor_kind GLOB '[a-z]*' "
            "AND actor_kind NOT GLOB '*[^a-z0-9_.]*' "
            "AND actor_kind NOT GLOB '*.[^a-z]*' "
            "AND actor_kind NOT LIKE '%..%' AND actor_kind NOT LIKE '%.'",
            "ck_economy_ledger_transactions_actor_kind",
        ),
        _sqlite_reference(
            "actor_reference",
            "ck_economy_ledger_transactions_actor_reference",
        ),
        _sqlite_check(
            "length(reason_code) BETWEEN 3 AND 100 AND instr(reason_code, char(0)) = 0 "
            "AND reason_code = lower(reason_code) AND reason_code GLOB '[a-z]*.[a-z]*' "
            "AND reason_code NOT GLOB '*[^a-z0-9_.]*' "
            "AND reason_code NOT GLOB '*.[^a-z]*' "
            "AND reason_code NOT LIKE '%..%' AND reason_code NOT LIKE '%.'",
            "ck_economy_ledger_transactions_reason_code",
        ),
        _sqlite_reference(
            "domain_reference",
            "ck_economy_ledger_transactions_domain_reference",
            nullable=True,
        ),
        _sqlite_reference(
            "content_version",
            "ck_economy_ledger_transactions_content_version",
            maximum=100,
            nullable=True,
        ),
        _sqlite_uuid("id"),
        _sqlite_integer("committed_at_ms"),
        _sqlite_uuid("correlation_id"),
        _sqlite_uuid("transport_request_id", nullable=True),
        _sqlite_integer("discord_interaction_id", nullable=True),
        UniqueConstraint("correlation_id", name="uq_economy_ledger_transactions_correlation"),
        Index(
            "ix_economy_ledger_transactions_committed_order",
            "committed_at_ms",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    transaction_kind: Mapped[str] = mapped_column(String(64))
    committed_at_ms: Mapped[int] = mapped_column(BigInteger)
    actor_kind: Mapped[str] = mapped_column(String(32))
    actor_reference: Mapped[str] = mapped_column(String(255))
    reason_code: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[UUID] = mapped_column(Uuid())
    transport_request_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    domain_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_interaction_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_version: Mapped[str | None] = mapped_column(String(100), nullable=True)


class LedgerPostingModel(Base):
    __tablename__ = "economy_ledger_postings"
    __table_args__ = (
        CheckConstraint("amount != 0", name="ck_economy_ledger_postings_nonzero"),
        _sqlite_uuid("transaction_id"),
        _sqlite_uuid("account_id"),
        _sqlite_integer("amount"),
    )

    transaction_id: Mapped[UUID] = mapped_column(
        Uuid(),
        ForeignKey("economy_ledger_transactions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("economy_accounts.id", ondelete="RESTRICT"), primary_key=True
    )
    amount: Mapped[int] = mapped_column(BigInteger)


class SafetyBootstrapModel(Base):
    __tablename__ = "safety_bootstrap"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_safety_bootstrap_once"),
        _sqlite_integer("id"),
        _sqlite_integer("created_at_ms"),
        CheckConstraint("created_at_ms >= 0", name="ck_safety_bootstrap_time"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)


class CapabilityModel(Base):
    __tablename__ = "safety_capabilities"
    __table_args__ = (
        CheckConstraint("actor_id > 0", name="ck_safety_capability_actor"),
        CheckConstraint(
            (
                "capability IN "
                "('capabilities.manage','players.inspect','restrictions.manage','proposals.approve','grants.propose')"
            ),
            name="ck_safety_capability_name",
        ),
        _sqlite_integer("actor_id"),
    )
    actor_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    capability: Mapped[str] = mapped_column(String(32), primary_key=True)


class RestrictionModel(Base):
    __tablename__ = "safety_restrictions"
    __table_args__ = (
        CheckConstraint("target_id >= 0", name="ck_safety_restriction_target"),
        _sqlite_integer("target_id"),
    )
    # Zero is the explicit global full-freeze target; positive values are Discord identities.
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class ProposalModel(Base):
    __tablename__ = "safety_proposals"
    __table_args__ = (
        CheckConstraint(
            (
                "actor_id > 0 AND (approver_id IS NULL OR (approver_id > 0 AND "
                "approver_id != actor_id))"
            ),
            name="ck_safety_proposal_actors",
        ),
        CheckConstraint(
            "operation IN ('freeze','release','grant')", name="ck_safety_proposal_operation"
        ),
        CheckConstraint(
            "(operation = 'grant' AND amount > 0) OR (operation != 'grant' AND amount = 0)",
            name="ck_safety_proposal_amount",
        ),
        CheckConstraint(
            "length(reason) BETWEEN 1 AND 256 AND instr(reason, char(0)) = 0",
            name="ck_safety_proposal_reason",
        ),
        CheckConstraint(
            "created_at_ms >= 0 AND expires_at_ms > created_at_ms", name="ck_safety_proposal_time"
        ),
        CheckConstraint("requires_approval IN (0,1)", name="ck_safety_proposal_requires_approval"),
        CheckConstraint(
            "status IN ('pending','approved','applied')", name="ck_safety_proposal_status"
        ),
        CheckConstraint(
            (
                "(status = 'pending' AND approver_id IS NULL) OR (status != 'pending'"
                " AND (requires_approval = 0 OR approver_id IS NOT NULL))"
            ),
            name="ck_safety_proposal_approval",
        ),
        CheckConstraint(
            "status != 'applied' OR operation != 'grant'", name="ck_safety_proposal_no_issuance"
        ),
        _sqlite_uuid("id"),
        _sqlite_integer("actor_id"),
        _sqlite_integer("approver_id", nullable=True),
        _sqlite_integer("amount"),
        _sqlite_integer("created_at_ms"),
        _sqlite_integer("expires_at_ms"),
        _sqlite_integer("requires_approval"),
        Index("ix_safety_proposals_actor_time", "actor_id", "created_at_ms"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    operation: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(256))
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    expires_at_ms: Mapped[int] = mapped_column(BigInteger)
    requires_approval: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))
    approver_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ProposalTargetModel(Base):
    __tablename__ = "safety_proposal_targets"
    __table_args__ = (
        CheckConstraint("target_id >= 0", name="ck_safety_proposal_target"),
        _sqlite_uuid("proposal_id"),
        _sqlite_integer("target_id"),
    )
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("safety_proposals.id", ondelete="RESTRICT"), primary_key=True
    )
    target_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)


class AccessAuditModel(Base):
    __tablename__ = "safety_access_audit"
    __table_args__ = (
        CheckConstraint(
            "actor_id > 0 AND (target_id IS NULL OR target_id >= 0)",
            name="ck_safety_audit_actor_target",
        ),
        CheckConstraint("length(action) BETWEEN 1 AND 64", name="ck_safety_audit_action"),
        CheckConstraint(
            "length(reason) BETWEEN 1 AND 256 AND instr(reason, char(0)) = 0",
            name="ck_safety_audit_reason",
        ),
        CheckConstraint("created_at_ms >= 0", name="ck_safety_audit_time"),
        _sqlite_uuid("id"),
        _sqlite_uuid("proposal_id", nullable=True),
        _sqlite_integer("actor_id"),
        _sqlite_integer("target_id", nullable=True),
        _sqlite_integer("created_at_ms"),
        Index("ix_safety_audit_created", "created_at_ms", "id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proposal_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    reason: Mapped[str] = mapped_column(String(256))
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
