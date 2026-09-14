"""widen instagram_editorial_deliveries telegram id columns to bigint

Revision ID: b7d1f92a4e6c
Revises: a3f7c1e9b204
Create Date: 2026-09-14 21:10:00.000000

INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1 §12/§18: real bug found during the
production canary - `telegram_chat_id` (Integer) overflowed on the real supergroup id
(-1004297182444, well outside int32 range) AFTER the real Telegram send had already succeeded,
leaving that row stuck in PENDING despite a real, successful delivery. `decided_by_telegram_user_id`
has the same latent overflow risk (modern Telegram user ids routinely exceed int32) and is widened
proactively here even though it had not yet been hit. Purely additive/widening - no data loss, no
existing row's value changes meaning, `downgrade()` narrows back to Integer (safe only if no
stored value actually exceeds int32 - true for every row that could exist at the time this phase's
downgrade would ever run, since the bug the upgrade fixes had not yet been able to write a wide
value into an Integer column in the first place).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7d1f92a4e6c'
down_revision: Union[str, None] = 'a3f7c1e9b204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('instagram_editorial_deliveries', 'telegram_chat_id', type_=sa.BigInteger(), existing_type=sa.Integer())
    op.alter_column('instagram_editorial_deliveries', 'decided_by_telegram_user_id', type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    op.alter_column('instagram_editorial_deliveries', 'decided_by_telegram_user_id', type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column('instagram_editorial_deliveries', 'telegram_chat_id', type_=sa.Integer(), existing_type=sa.BigInteger())
