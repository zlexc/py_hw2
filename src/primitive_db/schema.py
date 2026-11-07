from primitive_db.constants import SUPPORTED_TYPES


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


def column_types(columns):
    """Return the schema's ordered mapping of column names to Python types."""
    return {
        name: SUPPORTED_TYPES[data_type]
        for name, data_type in (column.split(":") for column in columns)
    }


def validate_clause(columns, clause, *, allow_id=True):
    """Check one equality or assignment against the table schema."""
    if not isinstance(clause, dict) or len(clause) != 1:
        raise ValueError("требуется одно условие или присваивание")
    types = column_types(columns)
    for name, value in clause.items():
        if name not in types:
            raise ValueError(f'неизвестный столбец "{name}"')
        if name == "ID" and not allow_id:
            raise ValueError("ID доступен только для чтения")
        if type(value) is not types[name]:
            raise ValueError(f"{name}={value!r}")


def validate_table_data(columns, data):
    """Reject malformed rows and duplicate or invalid primary keys."""
    if not isinstance(data, list):
        raise ValueError("Данные таблицы должны быть JSON-массивом.")
    types = column_types(columns)
    ids = set()
    for row in data:
        if (
            not isinstance(row, dict)
            or row.keys() != types.keys()
            or any(type(row[name]) is not expected for name, expected in types.items())
        ):
            raise ValueError("Запись не соответствует схеме таблицы.")
        if row["ID"] <= 0 or row["ID"] in ids:
            raise ValueError("ID должны быть положительными и уникальными.")
        ids.add(row["ID"])
