from sqlalchemy import inspect, text

from db.models import Base
from db.session import engine

# create_all() only creates missing tables, not new columns on existing ones -
# columns added to an existing model after its table already exists need an
# explicit ALTER TABLE here to actually show up.
ADDED_COLUMNS = {
    "job_openings": [
        ("custom_description", "TEXT"),
        ("custom_prompt", "TEXT"),
    ],
}


def run_migration():
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if table not in inspector.get_table_names():
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, col_type in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))
                    print(f"Added column {table}.{name}")

    print(f"Database schema created/updated at {engine.url}")


if __name__ == "__main__":
    run_migration()
