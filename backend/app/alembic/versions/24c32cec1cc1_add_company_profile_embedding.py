"""add self_description and company profile embedding

Revision ID: 24c32cec1cc1
Revises: b35354525a43
Create Date: 2026-09-17 19:21:05.333937

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = '24c32cec1cc1'
down_revision = 'b35354525a43'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        'companyprofile',
        sa.Column(
            'self_description',
            sqlmodel.sql.sqltypes.AutoString(length=2000),
            nullable=True,
        ),
    )

    op.create_table(
        'companyprofileembedding',
        sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(), nullable=False),
        sa.Column('embedding_model', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_profile_id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['company_profile_id'], ['companyprofile.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_profile_id'),
    )


def downgrade():
    op.drop_table('companyprofileembedding')
    op.drop_column('companyprofile', 'self_description')
    # Extension is left installed — dropping it isn't required for a clean
    # downgrade and could affect other objects.
