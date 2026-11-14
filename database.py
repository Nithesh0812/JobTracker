from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker,declarative_base
import logging
import os
from dotenv import load_dotenv

from logging_config import log_event

load_dotenv()
DATABASE_URL=os.getenv("DATABASE_URL","sqlite:///./jobtracker.db")

# Postgres: give up connecting after this many seconds, so a dead database
# fails fast instead of hanging every request
DB_CONNECT_TIMEOUT=int(os.getenv("DB_CONNECT_TIMEOUT","3"))
# How long a request waits for a free pooled connection before giving up
DB_POOL_TIMEOUT=int(os.getenv("DB_POOL_TIMEOUT","5"))

if DATABASE_URL.startswith("sqlite"):
    # SQLite has no network connection to time out, and in-memory SQLite
    # ("sqlite://") uses a pool that doesn't accept pool_timeout
    engine_options={"connect_args":{"check_same_thread":False}}
else:
    engine_options={
        "connect_args":{"connect_timeout":DB_CONNECT_TIMEOUT},
        "pool_timeout":DB_POOL_TIMEOUT,
    }

engine=create_engine(DATABASE_URL,pool_pre_ping=True,**engine_options)

SessionLocal=sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base=declarative_base()

logger=logging.getLogger("jobtracker.db")


@event.listens_for(Engine,"handle_error")
def log_database_error(context):
    """Log every error the database driver raises, for any engine.

    Logs what kind of failure it was, never the SQL text, its parameters or the
    exception message: those can contain user data, hostnames or usernames.
    """
    driver_exc=context.original_exception
    # SQLAlchemy's class (IntegrityError, OperationalError...) is the same on
    # SQLite and Postgres; the driver's class is more specific on Postgres
    # (NotNullViolation, UniqueViolation...)
    wrapped=context.sqlalchemy_exception
    statement=(context.statement or "").strip()
    if context.is_pre_ping:
        operation="PING"
    elif statement:
        operation=statement.split(None,1)[0].upper()
    else:
        operation="CONNECT"
    log_event(
        logger,
        "db_error",
        # A stale pooled connection caught by pool_pre_ping is replaced
        # automatically, so it's a warning rather than an error
        logging.WARNING if context.is_pre_ping else logging.ERROR,
        error_type=type(wrapped).__name__ if wrapped is not None else type(driver_exc).__name__,
        driver_error=type(driver_exc).__name__,
        sqlstate=getattr(driver_exc,"pgcode",None),
        operation=operation,
        is_disconnect=context.is_disconnect,
    )