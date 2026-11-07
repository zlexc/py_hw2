from primitive_db.decorators import (
    confirm_action,
    create_cacher,
    handle_db_errors,
    log_time,
)
from primitive_db.schema import column_types, validate_table_data
from primitive_db.schema import normalize_columns as normalize_columns
from primitive_db.utils import load_table_data

_select_cache = create_cacher()


def clear_select_cache():
    """Release cached queries by creating a fresh closure."""
    global _select_cache
    _select_cache = create_cacher()


@handle_db_errors
def create_table(metadata, table_name, columns):
    """Add a valid table, leaving metadata untouched on validation errors."""
    if not isinstance(table_name, str) or not table_name.strip():
        raise ValueError(f"некорректное имя таблицы: {table_name!r}")
    if table_name in metadata:
        raise ValueError(f'Таблица "{table_name}" уже существует.')

    normalized = normalize_columns(columns)
    metadata[table_name] = normalized
    return metadata


@handle_db_errors
@confirm_action("удаление таблицы")
def drop_table(metadata, table_name):
    """Remove an existing table and return the same metadata dictionary."""
    if table_name not in metadata:
        raise KeyError(table_name)

    del metadata[table_name]
    return metadata


@handle_db_errors
@log_time
def insert(metadata, table_name, values, table_data=None):
    """Return rows with a new, schema-checked record and an automatic ID."""
    if table_name not in metadata:
        raise KeyError(table_name)
    types = column_types(metadata[table_name])
    value_columns = [name for name in types if name != "ID"]
    if len(values) != len(value_columns):
        raise ValueError(
            f"ожидается значений: {len(value_columns)}, получено: {len(values)}"
        )
    for name, value in zip(value_columns, values):
        if type(value) is not types[name]:
            raise ValueError(f"{name}={value!r}")

    if table_data is None:
        table_data = load_table_data(table_name)
    validate_table_data(metadata[table_name], table_data)
    next_id = max((row["ID"] for row in table_data), default=0) + 1
    record = {"ID": next_id, **dict(zip(value_columns, values))}
    return [row.copy() for row in table_data] + [record]


def _matches(row, where_clause):
    return all(
        name in row and type(row[name]) is type(value) and row[name] == value
        for name, value in where_clause.items()
    )


def matching_rows(table_data, where_clause=None):
    """Share row filtering without timing or query-cache side effects."""
    return [
        row.copy()
        for row in table_data
        if where_clause is None or _matches(row, where_clause)
    ]


def _select_key(table_data, where_clause):
    rows = tuple(
        tuple((name, type(value), value) for name, value in row.items())
        for row in table_data
    )
    condition = (
        None
        if where_clause is None
        else tuple(
            sorted((name, type(value), value) for name, value in where_clause.items())
        )
    )
    return rows, condition


@handle_db_errors
@log_time
def select(table_data, where_clause=None):
    """Cache exact input snapshots and return independent row dictionaries."""
    rows = _select_cache(
        _select_key(table_data, where_clause),
        lambda: matching_rows(table_data, where_clause),
    )
    return [row.copy() for row in rows]


@handle_db_errors
def update(table_data, set_clause, where_clause):
    """Update matching rows without modifying the input or primary keys."""
    if "ID" in set_clause:
        raise ValueError("ID доступен только для чтения")
    return [
        {**row, **set_clause} if _matches(row, where_clause) else row.copy()
        for row in table_data
    ]


@handle_db_errors
@confirm_action("удаление записей")
def delete(table_data, where_clause):
    """Return copies of rows that do not match the equality."""
    return [row.copy() for row in table_data if not _matches(row, where_clause)]
