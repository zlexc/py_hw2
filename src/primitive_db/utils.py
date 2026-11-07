import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from primitive_db.core import normalize_columns


def load_metadata(filepath):
    """Load table schemas; a missing file represents an empty database."""
    try:
        with open(filepath, encoding="utf-8") as stream:
            metadata = json.load(stream)
    except FileNotFoundError:
        return {}

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
