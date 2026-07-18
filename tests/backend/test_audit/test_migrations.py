"""Model/migration parity (Step 16).

The Alembic-migrated schema and the SQLAlchemy models must describe the same
database: autogenerate against the migrated test database has to produce an
empty diff, otherwise a model change shipped without its migration (or vice
versa).
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.audit import db
from app.audit.models import Base, include_object_for_autogenerate


async def test_autogenerate_against_migrated_schema_is_an_empty_diff(audit_db):
    def diff(sync_connection):
        # include_object: the sqlite-vec virtual table and its shadow
        # tables (vec_*) are managed at runtime, not by Alembic, and may
        # exist in the shared test database once any vector test ran.
        context = MigrationContext.configure(
            sync_connection,
            opts={
                "compare_type": True,
                "include_object": include_object_for_autogenerate,
            },
        )
        return compare_metadata(context, Base.metadata)

    async with db.get_engine().connect() as connection:
        diffs = await connection.run_sync(diff)
    assert diffs == [], f"models and migrations have drifted: {diffs}"
