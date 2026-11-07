from primitive_db.schema import column_types, validate_table_data
from primitive_db.schema import normalize_columns as normalize_columns
from primitive_db.utils import load_table_data


def create_table(metadata, table_name, columns):
    """Add a valid table, leaving metadata untouched on validation errors."""
    if not isinstance(table_name, str) or not table_name.strip():
        print(f"Некорректное значение: {table_name}. Попробуйте снова.")
        return metadata
    if table_name in metadata:
        print(f'Ошибка: Таблица "{table_name}" уже существует.')
        return metadata

    try:
        normalized = normalize_columns(columns)
    except ValueError as error:
        print(f"Некорректное значение: {error}. Попробуйте снова.")
        return metadata

    metadata[table_name] = normalized
    return metadata


def drop_table(metadata, table_name):
    """Remove an existing table and return the same metadata dictionary."""
    if table_name not in metadata:
        print(f'Ошибка: Таблица "{table_name}" не существует.')
        return metadata

    del metadata[table_name]
    return metadata


def insert(metadata, table_name, values, table_data=None):
    """Return rows with a new, schema-checked record and an automatic ID."""
    if table_name not in metadata:
        raise ValueError(f'Таблица "{table_name}" не существует')
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


def select(table_data, where_clause=None):
    """Return copies of all rows, or only those matching the equality."""
    return [
        row.copy()
        for row in table_data
        if where_clause is None or _matches(row, where_clause)
    ]


def update(table_data, set_clause, where_clause):
    """Update matching rows without modifying the input or primary keys."""
    if "ID" in set_clause:
        raise ValueError("ID доступен только для чтения")
    return [
        {**row, **set_clause} if _matches(row, where_clause) else row.copy()
        for row in table_data
    ]


def delete(table_data, where_clause):
    """Return copies of rows that do not match the equality."""
    return [row.copy() for row in table_data if not _matches(row, where_clause)]
