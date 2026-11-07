import shlex

import prompt
from prettytable import PrettyTable

from primitive_db.core import (
    clear_select_cache,
    create_table,
    delete,
    drop_table,
    insert,
    matching_rows,
    select,
    update,
)
from primitive_db.decorators import handle_db_errors
from primitive_db.parser import parse_command
from primitive_db.schema import column_types, validate_clause, validate_table_data
from primitive_db.utils import (
    delete_table_data,
    load_metadata,
    load_table_data,
    save_metadata,
    save_table_data,
)

METADATA_FILE = "db_meta.json"
CRUD_COMMANDS = {"insert", "select", "update", "delete", "info"}


def print_help():
    print("\n***Процесс работы с таблицей***")
    print("Функции:")
    print("<command> create_table <имя_таблицы> <столбец1:тип> .. - создать таблицу")
    print("<command> list_tables - показать список всех таблиц")
    print("<command> drop_table <имя_таблицы> - удалить таблицу")
    print("\n***Операции с данными***")
    print("insert into <имя_таблицы> values (<значение1>, ...) - создать запись")
    print("select from <имя_таблицы> [where <столбец> = <значение>] - прочитать записи")
    print(
        "update <имя_таблицы> set <столбец> = <значение> where <столбец> = <значение>"
    )
    print("delete from <имя_таблицы> where <столбец> = <значение> - удалить записи")
    print("info <имя_таблицы> - информация о таблице")
    print("\nОбщие команды:")
    print("<command> exit - выход из программы")
    print("<command> help - справочная информация\n")


def _execute_table_command(metadata, command, arguments):
    table_name = arguments[0]
    if command == "drop_table" and table_name not in metadata:
        print(f'Ошибка: Таблица "{table_name}" не существует.')
        return 0
    previous_metadata = metadata.copy()
    if command == "create_table":
        result = create_table(metadata, table_name, arguments[1:])
    else:
        result = drop_table(metadata, table_name)
    if result is None or metadata == previous_metadata:
        return 0

    try:
        if command == "create_table":
            save_table_data(table_name, [])
        save_metadata(METADATA_FILE, metadata)
        if command == "drop_table":
            try:
                delete_table_data(table_name)
            except OSError:
                save_metadata(METADATA_FILE, previous_metadata)
                raise
    except (OSError, ValueError) as error:
        print(f"Ошибка: не удалось сохранить метаданные или данные таблицы: {error}")
        return 1

    clear_select_cache()
    if command == "create_table":
        columns = ", ".join(metadata[table_name])
        print(f'Таблица "{table_name}" успешно создана со столбцами: {columns}')
    else:
        print(f'Таблица "{table_name}" успешно удалена.')
    return 0


@handle_db_errors
def _validate_data_clauses(columns, parsed):
    where_clause = parsed.get("where_clause")
    if where_clause is not None:
        validate_clause(columns, where_clause)
    if parsed["command"] == "update":
        validate_clause(columns, parsed["set_clause"], allow_id=False)
    return True


def _execute_data_command(metadata, parsed):
    command = parsed["command"]
    table_name = parsed["table_name"]
    if table_name not in metadata:
        print(f'Ошибка: Таблица "{table_name}" не существует.')
        return 0
    columns = metadata[table_name]
    where_clause = parsed.get("where_clause")
    if _validate_data_clauses(columns, parsed) is None:
        return 0

    try:
        table_data = load_table_data(table_name)
        validate_table_data(columns, table_data)
    except (OSError, ValueError) as error:
        print(f'Ошибка: не удалось загрузить данные таблицы "{table_name}": {error}')
        return 1

    if command == "info":
        print(f"Таблица: {table_name}")
        print(f"Столбцы: {', '.join(columns)}")
        print(f"Количество записей: {len(table_data)}")
        return 0
    if command == "select":
        rows = select(table_data, where_clause)
        if rows is None:
            return 0
        table = PrettyTable(field_names=list(column_types(columns)))
        for row in rows:
            table.add_row([row[name] for name in table.field_names])
        print(table)
        return 0

    matches = matching_rows(table_data, where_clause) if command != "insert" else []
    if command in {"update", "delete"} and not matches:
        print("Подходящие записи не найдены.")
        return 0
    if command == "insert":
        result = insert(metadata, table_name, parsed["values"], table_data)
    elif command == "update":
        result = update(table_data, parsed["set_clause"], where_clause)
    else:
        result = delete(table_data, where_clause)
    if result is None:
        return 0

    if result != table_data:
        try:
            save_table_data(table_name, result)
        except (OSError, ValueError) as error:
            print(
                f'Ошибка: не удалось сохранить данные таблицы "{table_name}": {error}'
            )
            return 1
        clear_select_cache()

    if command == "insert":
        record_id = result[-1]["ID"]
        print(f'Запись с ID={record_id} успешно добавлена в таблицу "{table_name}".')
    else:
        for row in matches:
            if command == "update":
                print(
                    f'Запись с ID={row["ID"]} в таблице "{table_name}" '
                    "успешно обновлена."
                )
            else:
                print(
                    f"Запись с ID={row['ID']} успешно удалена "
                    f'из таблицы "{table_name}".'
                )
    return 0


def run():
    """Read commands and persist successful schema and row operations."""
    clear_select_cache()
    print_help()

    while True:
        try:
            metadata = load_metadata(METADATA_FILE)
        except (OSError, ValueError) as error:
            print(f"Ошибка: не удалось загрузить метаданные: {error}")
            return 1

        try:
            user_input = prompt.string(">>>Введите команду: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        first_word = user_input.split(maxsplit=1)
        if first_word and first_word[0] in CRUD_COMMANDS:
            try:
                parsed = parse_command(user_input)
            except ValueError as error:
                print(f"Некорректное значение: {error}. Попробуйте снова.")
                continue
            if _execute_data_command(metadata, parsed):
                return 1
            continue

        try:
            tokens = shlex.split(user_input)
        except ValueError:
            print(f"Некорректное значение: {user_input}. Попробуйте снова.")
            continue
        if not tokens:
            continue
        command, *arguments = tokens

        if command in {"exit", "help", "list_tables"}:
            if arguments:
                print(f"Некорректное значение: {user_input}. Попробуйте снова.")
                continue
            if command == "exit":
                return 0
            if command == "help":
                print_help()
            elif metadata:
                for table_name in metadata:
                    print(f"- {table_name}")
            else:
                print("Таблиц пока нет.")
            continue

        if command not in {"create_table", "drop_table"}:
            print(f"Функции {command} нет. Попробуйте снова.")
            continue
        if (command == "create_table" and len(arguments) < 2) or (
            command == "drop_table" and len(arguments) != 1
        ):
            print(f"Некорректное значение: {user_input}. Попробуйте снова.")
            continue

        if _execute_table_command(metadata, command, arguments):
            return 1
