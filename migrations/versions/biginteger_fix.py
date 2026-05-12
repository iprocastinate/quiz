"""use_biginteger

Revision ID: biginteger_fix
Revises: 87f3972b86f9
Create Date: 2026-05-12 14:48:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'biginteger_fix'
down_revision = '87f3972b86f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Change columns to BigInteger
    op.alter_column('conversation_states', 'chat_id', type_=sa.BigInteger())
    op.alter_column('conversation_states', 'user_id', type_=sa.BigInteger())
    op.alter_column('user_data', 'user_id', type_=sa.BigInteger())


def downgrade() -> None:
    op.alter_column('conversation_states', 'chat_id', type_=sa.Integer())
    op.alter_column('conversation_states', 'user_id', type_=sa.Integer())
    op.alter_column('user_data', 'user_id', type_=sa.Integer())
