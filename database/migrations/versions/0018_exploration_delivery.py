"""Pin exploration delivery snapshots and allow worker session finalization."""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0018_exploration_delivery"
down_revision: str | None = "0017_idempotency_key_reuse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("explorations", sa.Column("delivery_snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("explorations", sa.Column("delivery_contract_version", sa.Text(), nullable=True))
    op.create_check_constraint("ck_explorations_explorations_delivery_pair", "explorations", "(delivery_snapshot is null) = (delivery_contract_version is null)")
    op.execute("""
        create function public.guard_exploration_delivery() returns trigger
        language plpgsql set search_path = pg_catalog, public as $$
        begin
          if new.entity_id is distinct from old.entity_id
             or new.entity_version is distinct from old.entity_version
             or new.user_id is distinct from old.user_id
             or new.id is distinct from old.id then
            raise exception 'exploration identity is immutable' using errcode = '23514';
          end if;
          if old.delivery_snapshot is not null and
             (new.delivery_snapshot is distinct from old.delivery_snapshot
              or new.delivery_contract_version is distinct from old.delivery_contract_version) then
            raise exception 'prepared delivery is immutable' using errcode = '23514';
          end if;
          return new;
        end $$
    """)
    op.execute("create trigger trg_exploration_delivery_guard before update on public.explorations for each row execute function public.guard_exploration_delivery()")
    op.execute("revoke all on function public.guard_exploration_delivery() from public")
    op.execute("grant update (status, completed_at) on public.assessment_sessions to app_worker")


def downgrade() -> None:
    op.execute("revoke update (status, completed_at) on public.assessment_sessions from app_worker")
    op.execute("drop trigger trg_exploration_delivery_guard on public.explorations")
    op.execute("drop function public.guard_exploration_delivery()")
    op.drop_constraint("ck_explorations_explorations_delivery_pair", "explorations", type_="check")
    op.drop_column("explorations", "delivery_contract_version")
    op.drop_column("explorations", "delivery_snapshot")
