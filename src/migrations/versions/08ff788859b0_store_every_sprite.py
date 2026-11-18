"""store every sprite

Revision ID: 08ff788859b0
Revises: 5241aebe9401
Create Date: 2026-11-17 13:10:00.230617

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08ff788859b0'
down_revision: Union[str, Sequence[str], None] = '5241aebe9401'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """one row per sprite file instead of one png and one gif per pokemon.
    autogenerate missed the primary key change, so the table is dropped and recreated.
    the old rows can't be converted (they have no sprite_key), the next run refills the table."""
    op.drop_table('sprites')
    op.create_table('sprites',
    sa.Column('pokemon_id', sa.Integer(), nullable=False),
    sa.Column('sprite_key', sa.Text(), nullable=False),
    sa.Column('format', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=False),
    sa.Column('local_path', sa.Text(), nullable=False),
    sa.Column('gcs_uri', sa.Text(), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('checksum', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['pokemon_id'], ['pokemon.id'], name=op.f('fk_sprites_pokemon_id_pokemon')),
    sa.PrimaryKeyConstraint('pokemon_id', 'sprite_key', name=op.f('pk_sprites'))
    )


def downgrade() -> None:
    """back to one png and one gif per pokemon"""
    op.drop_table('sprites')
    op.create_table('sprites',
    sa.Column('pokemon_id', sa.Integer(), nullable=False),
    sa.Column('format', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('gcs_uri', sa.Text(), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('checksum', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['pokemon_id'], ['pokemon.id'], name=op.f('fk_sprites_pokemon_id_pokemon')),
    sa.PrimaryKeyConstraint('pokemon_id', 'format', name=op.f('pk_sprites'))
    )