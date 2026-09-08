from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config

# SQLite serializes writes at the file level; with candidates now processed
# concurrently (see main.py's thread pool) two threads can genuinely try to
# write at the same instant. A busy timeout makes SQLite retry for a bit
# instead of immediately raising "database is locked".
connect_args = {"timeout": 30} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
