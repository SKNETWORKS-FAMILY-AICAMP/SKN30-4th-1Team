import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()


def _connection_kwargs() -> dict:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "database": os.getenv("DB_NAME", "paiM"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def get_connection():
    """Return the ordinary application connection without readiness deadlines."""
    return pymysql.connect(**_connection_kwargs())


def get_readiness_connection():
    """Return a connection bounded for the readiness probe only."""
    return pymysql.connect(
        **_connection_kwargs(),
        connect_timeout=2,
        read_timeout=2,
        write_timeout=2,
    )
