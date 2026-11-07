SUPPORTED_TYPES = {"int", "str", "bool"}


def normalize_columns(columns):
    """Validate column definitions and put the unique ID column first."""
    if not columns:
        raise ValueError("столбцы не заданы")

    names = set()
    normalized = ["ID:int"]
    for column in columns:
        if not isinstance(column, str) or column.count(":") != 1:
            raise ValueError(column)
        name, data_type = column.split(":")
        if (
            not name.strip()
            or name in names
            or data_type not in SUPPORTED_TYPES
            or (name == "ID" and data_type != "int")
        ):
            raise ValueError(column)
        names.add(name)
        if name != "ID":
            normalized.append(column)

    return normalized


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
