"""add instagram account read metadata

Revision ID: 4a1b7c9d2e3f
Revises: b548f44f0f85
Create Date: 2026-09-08 18:00:00.000000

DIRECTOR-CONTROL-PLANE-1C §13/§16/§19/§27: purely additive, all-nullable columns on the existing
`instagram_accounts` table - non-secret profile-presentation metadata (biography,
profile_picture_url, account_type, follower/follows/media counts) plus read-health metadata
(last_successful_read_at, last_read_error, access_token_status, access_token_expires_at) plus a
detected per-capability map (capabilities JSON).

Why reuse was not possible (§27): the pre-1C `instagram_accounts` table stored only identity
(ig_user_id/username), connection_state, and last_sync_at. There was no column for profile
presentation, audience counts, capability-detection results, or read-health, and no generic
account-metadata store exists elsewhere to reuse. §13 requires the profile metadata to reach the
Instagram Directors from cache, and §19 requires all of it to render in `/accounts` WITHOUT a live
network call - neither is representable in the existing schema.

NO token / app-secret column is added anywhere (§7/§24): the access token lives only in
`settings.instagram_access_token` (SecretStr) and is never persisted.

Local/test database only - not applied to production as part of this phase.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a1b7c9d2e3f"
down_revision: Union[str, None] = "b548f44f0f85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = (
    ("biography", sa.Text()),
    ("profile_picture_url", sa.String(length=2048)),
    ("account_type", sa.String(length=64)),
    ("followers_count", sa.Integer()),
    ("follows_count", sa.Integer()),
    ("media_count", sa.Integer()),
    ("last_successful_read_at", sa.DateTime(timezone=True)),
    ("last_read_error", sa.String(length=256)),
    ("access_token_status", sa.String(length=16)),
    ("access_token_expires_at", sa.DateTime(timezone=True)),
    ("capabilities", postgresql.JSON(astext_type=sa.Text())),
)


def upgrade() -> None:
    for name, column_type in _NEW_COLUMNS:
        op.add_column("instagram_accounts", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(_NEW_COLUMNS):
        op.drop_column("instagram_accounts", name)
