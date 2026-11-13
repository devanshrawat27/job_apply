"""SQLAlchemy engine, session factory, and declarative base."""

from sqlalchemy import JSON, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def _connect_args() -> dict:
    if settings.database_url.startswith("sqlite"):
        # SQLite is used by multiple threads (scheduler + request handlers).
        # The timeout makes concurrent writes wait instead of failing with
        # "database is locked".
        return {"check_same_thread": False, "timeout": 30}
    return {}


engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(),
    pool_pre_ping=True,
    future=True,
)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _column_default_sql(column) -> str:
    """A DEFAULT clause SQLite accepts when adding a NOT NULL column."""
    if isinstance(column.type, JSON):
        return " DEFAULT '[]'"
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        python_type = str

    if python_type is bool:
        return " DEFAULT 0"
    if python_type in (int, float):
        return " DEFAULT 0"
    if python_type in (list, dict):
        return " DEFAULT '[]'"
    return " DEFAULT ''"


def ensure_schema() -> None:
    """Add missing columns to an existing SQLite database.

    Keeps your data when the app gains fields, instead of forcing a reset.
    Only additive, nullable-safe changes are made; nothing is dropped.
    """
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or column.primary_key:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                default_sql = "" if column.nullable else _column_default_sql(column)
                connection.execute(
                    text(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" '
                        f"{ddl_type}{default_sql}"
                    )
                )
