from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config

# SQLite serializes writes at the file level; with candidates now processed
# concurrently (see main.py's thread pool) two threads can genuinely try to
# write at the same instant. A busy timeout makes SQLite retry for a bit
# instead of immediately raising "database is locked".
connect_args = {"timeout": 30} if config.DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping matters a lot for Neon (or any autosuspending Postgres) -
# Neon suspends its compute after a period of no activity, which silently
# kills any connection SQLAlchemy's pool was holding onto. Without
# pre-ping, the next query on that stale connection fails outright with
# "psycopg2.OperationalError: SSL connection has been closed unexpectedly"
# (confirmed live on the deployed backend) instead of SQLAlchemy quietly
# reconnecting. pre_ping issues a lightweight test query before handing a
# pooled connection to a caller and transparently reconnects if it's dead.
# pool_recycle proactively drops connections older than 5 minutes even if
# pre-ping hasn't caught them yet, since Neon's free-tier autosuspend
# window can be shorter than a long-idle SQLAlchemy pool would otherwise
# assume. Harmless (near-zero overhead) for local SQLite too, so applied
# unconditionally rather than only for Postgres.
engine = create_engine(
    config.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
