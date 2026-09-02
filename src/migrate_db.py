from db.models import Base
from db.session import engine


def run_migration():
    Base.metadata.create_all(engine)
    print(f"Database schema created/updated at {engine.url}")


if __name__ == "__main__":
    run_migration()
