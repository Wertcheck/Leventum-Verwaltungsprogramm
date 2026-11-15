from alembic import context
from sqlalchemy import create_engine

from leventum.db.base import Base
import leventum.models  # noqa: F401

target_metadata = Base.metadata


def run() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run()
