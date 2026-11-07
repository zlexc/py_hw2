"""Shared storage settings and supported database operations."""

from pathlib import Path

METADATA_FILE = "db_meta.json"
DATA_DIR = Path("data")
SUPPORTED_TYPES = {"int": int, "str": str, "bool": bool}
CRUD_COMMANDS = frozenset({"insert", "select", "update", "delete", "info"})
SAFE_FILENAME_BYTES = b"abcdefghijklmnopqrstuvwxyz0123456789_-"
