import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from primitive_db.constants import DATA_DIR, SAFE_FILENAME_BYTES
from primitive_db.schema import normalize_columns


def _load_json(filepath, default):
    """Read JSON, using the supplied default only when the file is missing."""
    try:
        with open(filepath, encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return default


def load_metadata(filepath):
    """Load table schemas; a missing file represents an empty database."""
    metadata = _load_json(filepath, {})
    if not isinstance(metadata, dict):
        raise ValueError("Метаданные должны быть JSON-объектом.")
    for table_name, columns in metadata.items():
        if (
            not table_name.strip()
            or not isinstance(columns, list)
            or normalize_columns(columns) != columns
        ):
            raise ValueError(f'Некорректная структура таблицы "{table_name}".')
    return metadata


def save_metadata(filepath, data):
    """Persist metadata using the same atomic writer as table data."""
    _save_json(filepath, data)


def _save_json(filepath, data):
    """Replace the JSON file only after the complete new version is written."""
    filepath = Path(filepath)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=filepath.parent,
            prefix=f".{filepath.name}.",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary_path.replace(filepath)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def table_data_path(table_name):
    """Encode names as distinct filenames, even on case-insensitive systems."""
    filename = "".join(
        chr(byte) if byte in SAFE_FILENAME_BYTES else f"%{byte:02X}"
        for byte in table_name.encode("utf-8")
    )
    return DATA_DIR / f"{filename}.json"


def load_table_data(table_name):
    """Load row dictionaries; the caller validates them against the schema."""
    data = _load_json(table_data_path(table_name), [])
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("Данные таблицы должны быть массивом записей.")
    return data


def save_table_data(table_name, data):
    """Create the data directory and atomically save a table's rows."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _save_json(table_data_path(table_name), data)


def delete_table_data(table_name):
    """Remove only this table's encoded data file, if it exists."""
    table_data_path(table_name).unlink(missing_ok=True)
