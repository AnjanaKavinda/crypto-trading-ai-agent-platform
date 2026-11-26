"""Allow C-107v2 snapshot-linked declarations in the journal index (E2c2)."""

from alembic import op

revision = "0014_journal_snapshot_link"
down_revision = "0013_owner_trade_outcomes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive: widens the allowed schema versions; existing v1 rows still match.
    op.drop_constraint(
        "ck_journal_request_scope", "research_journal_requests", type_="check"
    )
    op.create_check_constraint(
        "ck_journal_request_scope",
        "research_journal_requests",
        "profile = 'PERSONAL_SPOT_RESEARCH' AND contract_id = 'C-107' "
        "AND version IN ('1', '2')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for retained research declarations."
    )
