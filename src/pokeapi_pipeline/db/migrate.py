from alembic import command
from alembic.config import Config

from pokeapi_pipeline.util.config import ROOT

def upgrade_to_head() -> None:
    """apply every pending migration, does nothing when the schema is current"""
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")