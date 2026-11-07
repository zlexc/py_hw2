import shlex

import prompt

from primitive_db.core import create_table, drop_table
from primitive_db.utils import load_metadata, save_metadata

METADATA_FILE = "db_meta.json"


def print_help():
    print("\n***Процесс работы с таблицей***")
    print("Функции:")
    print("<command> create_table <имя_таблицы> <столбец1:тип> .. - создать таблицу")
    print("<command> list_tables - показать список всех таблиц")
    print("<command> drop_table <имя_таблицы> - удалить таблицу")
    print("\nОбщие команды:")
    print("<command> exit - выход из программы")
    print("<command> help - справочная информация\n")


def run():
    """Read commands and persist successful table operations."""
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

        table_name = arguments[0]
        previous_metadata = metadata.copy()
        if command == "create_table":
            create_table(metadata, table_name, arguments[1:])
        else:
            drop_table(metadata, table_name)
        if metadata == previous_metadata:
            continue

        try:
            save_metadata(METADATA_FILE, metadata)
        except (OSError, ValueError) as error:
            print(f"Ошибка: не удалось сохранить метаданные: {error}")
            return 1

        if command == "create_table":
            columns = ", ".join(metadata[table_name])
            print(f'Таблица "{table_name}" успешно создана со столбцами: {columns}')
        else:
            print(f'Таблица "{table_name}" успешно удалена.')
