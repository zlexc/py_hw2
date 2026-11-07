import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from primitive_db.core import clear_select_cache, matching_rows
from primitive_db.engine import run
from primitive_db.utils import (
    load_metadata,
    load_table_data,
    save_metadata,
    save_table_data,
    table_data_path,
)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filepath = Path(self.directory.name) / "db_meta.json"
        self.data_dir = Path(self.directory.name) / "data"
        data_patch = patch("primitive_db.utils.DATA_DIR", self.data_dir)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def seed_users(self, rows=None):
        save_metadata(
            self.filepath,
            {"users": ["ID:int", "name:str", "age:int", "is_active:bool"]},
        )
        save_table_data("users", [] if rows is None else rows)

    def run_commands(self, commands, *, answers=None):
        output = io.StringIO()
        inputs = commands if callable(commands) else [*commands, EOFError]
        with (
            patch("primitive_db.engine.METADATA_FILE", self.filepath),
            patch("primitive_db.engine.prompt.string", side_effect=inputs),
            patch(
                "builtins.input", return_value="y", side_effect=answers
            ) as confirmation,
            redirect_stdout(output),
        ):
            status = run()
        self.confirmation = confirmation
        return status, output.getvalue()

    def test_full_table_lifecycle_and_success_messages(self):
        status, output = self.run_commands(
            [
                "create_table users name:str age:int is_active:bool",
                "create_table users name:str",
                "list_tables",
                "drop_table users",
                "drop_table products",
                "list_tables",
                "exit",
            ]
        )
        self.assertEqual(status, 0)
        self.assertIn(
            'Таблица "users" успешно создана со столбцами: '
            "ID:int, name:str, age:int, is_active:bool",
            output,
        )
        self.assertIn('Ошибка валидации: Таблица "users" уже существует.', output)
        self.assertIn("- users\n", output)
        self.assertIn('Таблица "users" успешно удалена.', output)
        self.assertIn('Ошибка: Таблица "products" не существует.', output)
        self.assertIn("Таблиц пока нет.", output)
        self.assertEqual(load_metadata(self.filepath), {})

    def test_quoted_names_and_persistence_across_runs(self):
        status, _ = self.run_commands(
            ['create_table "active users" "full name:str" ID:int', "exit"]
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            load_metadata(self.filepath), {"active users": ["ID:int", "full name:str"]}
        )
        status, output = self.run_commands(["list_tables", "exit"])
        self.assertEqual(status, 0)
        self.assertIn("- active users\n", output)

    def test_bad_commands_recover_without_writing_metadata(self):
        commands = [
            "unknown",
            'create_table "users',
            "create_table",
            "create_table users",
            "drop_table",
            "drop_table users extra",
            "help extra",
            "exit extra",
            "list_tables extra",
            "create_table users age:float",
            'create_table "" name:str',
            "",
            "   ",
            "help",
            "exit",
        ]
        with patch("primitive_db.engine.save_metadata") as save:
            status, output = self.run_commands(commands)
        self.assertEqual(status, 0)
        self.assertIn("Функции unknown нет. Попробуйте снова.", output)
        self.assertEqual(
            output.count("Некорректное значение:") + output.count("Ошибка валидации:"),
            10,
        )
        self.assertEqual(output.count("***Процесс работы с таблицей***"), 2)
        save.assert_not_called()
        self.assertFalse(self.filepath.exists())

    def test_only_successful_mutations_are_saved(self):
        with patch("primitive_db.engine.save_metadata", wraps=save_metadata) as save:
            status, _ = self.run_commands(
                [
                    "create_table users ID:int",
                    "create_table users name:str",
                    "create_table invalid age:float",
                    "help",
                    "list_tables",
                    "drop_table missing",
                    "drop_table users",
                    "exit",
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(save.call_count, 2)

    def test_metadata_is_reloaded_on_every_iteration(self):
        with patch(
            "primitive_db.engine.load_metadata",
            side_effect=[{}, {"external": ["ID:int"]}, {}],
        ) as load:
            status, output = self.run_commands(["list_tables", "list_tables", "exit"])
        self.assertEqual(status, 0)
        self.assertIn("Таблиц пока нет.", output)
        self.assertIn("- external\n", output)
        self.assertEqual(load.call_count, 3)

    def test_eof_and_keyboard_interrupt_exit_cleanly(self):
        for interrupt in (EOFError, KeyboardInterrupt):
            with self.subTest(interrupt=interrupt):
                status, _ = self.run_commands([interrupt])
                self.assertEqual(status, 0)

    def test_corrupt_metadata_is_preserved_and_prevents_input(self):
        for content in ("{broken", json.dumps({"users": ["name:str"]})):
            with self.subTest(content=content):
                self.filepath.write_text(content, encoding="utf-8")
                status, output = self.run_commands([])
                self.assertEqual(status, 1)
                self.assertIn("не удалось загрузить метаданные", output)
                self.assertEqual(self.filepath.read_text(encoding="utf-8"), content)

    def test_read_error_returns_failure(self):
        with patch(
            "primitive_db.engine.load_metadata", side_effect=PermissionError("denied")
        ):
            status, output = self.run_commands(["exit"])
        self.assertEqual(status, 1)
        self.assertIn("не удалось загрузить метаданные", output)

    def test_write_error_does_not_report_success(self):
        with patch(
            "primitive_db.engine.save_metadata", side_effect=OSError("disk full")
        ):
            status, output = self.run_commands(["create_table users ID:int"])
        self.assertEqual(status, 1)
        self.assertIn("не удалось сохранить метаданные", output)
        self.assertNotIn('Таблица "users" успешно создана', output)

    def test_full_crud_lifecycle_survives_restart(self):
        self.seed_users()
        status, output = self.run_commands(
            ['insert into users values ("Sergei", 28, true)', "exit"]
        )
        self.assertEqual(status, 0)
        self.assertIn('Запись с ID=1 успешно добавлена в таблицу "users".', output)
        status, output = self.run_commands(
            [
                "select from users where age=28",
                'update users set age=29 where name="Sergei"',
                "select from users",
                "delete from users where ID=1",
                "info users",
                "exit",
            ]
        )
        self.assertEqual(status, 0)
        self.assertIn("| ID |", output)
        self.assertIn("Sergei", output)
        self.assertIn('Запись с ID=1 в таблице "users" успешно обновлена.', output)
        self.assertIn('Запись с ID=1 успешно удалена из таблицы "users".', output)
        self.assertIn("Количество записей: 0", output)
        self.assertEqual(load_table_data("users"), [])

    def test_update_and_delete_affect_all_matches(self):
        self.seed_users(
            [
                {"ID": 1, "name": "A", "age": 28, "is_active": True},
                {"ID": 2, "name": "B", "age": 28, "is_active": False},
            ]
        )
        status, output = self.run_commands(
            [
                "update users set age=29 where age=28",
                "delete from users where age=29",
                "exit",
            ]
        )
        self.assertEqual(status, 0)
        self.assertEqual(output.count("успешно обновлена."), 2)
        self.assertEqual(output.count("успешно удалена из таблицы"), 2)
        self.assertEqual(load_table_data("users"), [])

    def test_invalid_crud_commands_leave_file_unchanged(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        original = table_data_path("users").read_bytes()
        with patch("primitive_db.engine.save_table_data") as save:
            status, output = self.run_commands(
                [
                    'insert into users values ("B", "28", true)',
                    'insert into users values ("B", true, true)',
                    'insert into users values ("B", 28, 1)',
                    'insert into users values ("B", 28)',
                    'insert into users values (2, "B", 28, true)',
                    "update users set ID=2 where ID=1",
                    "update users set missing=29 where ID=1",
                    'update users set age="29" where ID=1',
                    "delete from users where missing=1",
                    "delete from users where ID=true",
                    'select from users where age="28"',
                    "select from missing",
                    "info missing",
                    "select from users where age > 1",
                    'insert into users values ("unclosed)',
                    "delete from users",
                    "update users set age=29, name='B' where ID=1",
                    "exit",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("ID доступен только для чтения", output)
        self.assertIn('Ошибка: Таблица "missing" не существует.', output)
        save.assert_not_called()
        self.assertEqual(table_data_path("users").read_bytes(), original)

    def test_empty_select_and_no_matches_do_not_write(self):
        self.seed_users()
        with patch("primitive_db.engine.save_table_data") as save:
            status, output = self.run_commands(
                [
                    "select from users",
                    "update users set age=29 where ID=1",
                    "delete from users where ID=1",
                    "info users",
                    "exit",
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn("| ID | name | age | is_active |", output)
        self.assertEqual(output.count("Подходящие записи не найдены."), 2)
        self.assertIn("Количество записей: 0", output)
        save.assert_not_called()

    def test_update_to_same_value_does_not_rewrite(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        with patch("primitive_db.engine.save_table_data") as save:
            status, output = self.run_commands(["update users set age=28 where ID=1"])
        self.assertEqual(status, 0)
        self.assertIn("успешно обновлена.", output)
        save.assert_not_called()

    def test_quoted_names_and_escaped_values_work_through_engine(self):
        status, output = self.run_commands(
            [
                'create_table "active users" "full name:str"',
                r"""insert into "active users" values ('it\'s, where = (set)')""",
                'select from "active users" where "full name"='
                r"'it\'s, where = (set)'",
                "exit",
            ]
        )
        self.assertEqual(status, 0)
        self.assertIn("it's, where = (set)", output)
        self.assertEqual(
            load_table_data("active users"),
            [{"ID": 1, "full name": "it's, where = (set)"}],
        )

    def test_drop_removes_rows_and_recreation_is_empty(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        status, _ = self.run_commands(["drop_table users", "exit"])
        self.assertEqual(status, 0)
        self.assertFalse(table_data_path("users").exists())
        status, _ = self.run_commands(["create_table users name:str", "exit"])
        self.assertEqual(status, 0)
        self.assertTrue(table_data_path("users").exists())
        self.assertEqual(load_table_data("users"), [])

    def test_duplicate_create_does_not_clear_rows(self):
        rows = [{"ID": 1, "name": "A", "age": 28, "is_active": True}]
        self.seed_users(rows)
        status, _ = self.run_commands(["create_table users ID:int", "exit"])
        self.assertEqual(status, 0)
        self.assertEqual(load_table_data("users"), rows)

    def test_id_only_table_accepts_empty_values(self):
        status, _ = self.run_commands(
            ["create_table ids ID:int", "insert into ids values ()", "exit"]
        )
        self.assertEqual(status, 0)
        self.assertEqual(load_table_data("ids"), [{"ID": 1}])

    def test_case_sensitive_names_have_independent_data(self):
        status, _ = self.run_commands(
            [
                "create_table users ID:int",
                "create_table Users ID:int",
                "insert into users values ()",
                "insert into Users values ()",
                "drop_table users",
                "exit",
            ]
        )
        self.assertEqual(status, 0)
        self.assertFalse(table_data_path("users").exists())
        self.assertEqual(load_table_data("Users"), [{"ID": 1}])

    def test_corrupt_rows_are_preserved_and_prevent_mutation(self):
        self.seed_users()
        for content in (
            "{broken",
            "{}",
            '[{"ID": 1}]',
            '[{"ID": 1, "name": "A", "age": true, "is_active": true}]',
            '[{"ID": true, "name": "A", "age": 28, "is_active": true}]',
        ):
            with self.subTest(content=content):
                table_data_path("users").write_text(content, encoding="utf-8")
                with patch("primitive_db.engine.save_table_data") as save:
                    status, output = self.run_commands(
                        ['insert into users values ("B", 28, false)']
                    )
                self.assertEqual(status, 1)
                self.assertIn("не удалось загрузить данные таблицы", output)
                save.assert_not_called()
                self.assertEqual(
                    table_data_path("users").read_text(encoding="utf-8"), content
                )

    def test_missing_data_file_is_an_empty_table(self):
        self.seed_users()
        table_data_path("users").unlink()
        status, output = self.run_commands(["info users", "exit"])
        self.assertEqual(status, 0)
        self.assertIn("Количество записей: 0", output)
        self.assertFalse(table_data_path("users").exists())

    def test_row_read_error_returns_failure(self):
        self.seed_users()
        with patch(
            "primitive_db.engine.load_table_data", side_effect=PermissionError("denied")
        ):
            status, output = self.run_commands(["select from users"])
        self.assertEqual(status, 1)
        self.assertIn("не удалось загрузить данные таблицы", output)

    def test_row_write_error_does_not_report_success(self):
        self.seed_users()
        with patch(
            "primitive_db.engine.save_table_data", side_effect=OSError("disk full")
        ):
            status, output = self.run_commands(
                ['insert into users values ("A", 28, true)']
            )
        self.assertEqual(status, 1)
        self.assertIn("не удалось сохранить данные таблицы", output)
        self.assertNotIn("успешно добавлена", output)
        self.assertEqual(load_table_data("users"), [])

    def test_create_data_file_failure_does_not_save_schema(self):
        with patch(
            "primitive_db.engine.save_table_data", side_effect=PermissionError("denied")
        ):
            status, output = self.run_commands(["create_table users ID:int"])
        self.assertEqual(status, 1)
        self.assertNotIn("успешно создана", output)
        self.assertEqual(load_metadata(self.filepath), {})

    def test_failed_drop_restores_schema_and_preserves_rows(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        with patch(
            "primitive_db.engine.delete_table_data",
            side_effect=PermissionError("denied"),
        ):
            status, output = self.run_commands(["drop_table users"])
        self.assertEqual(status, 1)
        self.assertNotIn('Таблица "users" успешно удалена.', output)
        self.assertIn("users", load_metadata(self.filepath))
        self.assertEqual(len(load_table_data("users")), 1)

    def test_cancelled_deletions_preserve_files_without_reporting_success(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        original_metadata = self.filepath.read_bytes()
        original_rows = table_data_path("users").read_bytes()
        with (
            patch("primitive_db.engine.save_metadata") as save_schema,
            patch("primitive_db.engine.save_table_data") as save_rows,
            patch("primitive_db.engine.delete_table_data") as remove_rows,
        ):
            status, output = self.run_commands(
                [
                    "delete from users where ID=1",
                    "drop_table users",
                    "info users",
                    "exit",
                ],
                answers=["n", "n"],
            )
        self.assertEqual(status, 0)
        self.assertEqual(output.count("Операция отменена."), 2)
        self.assertNotIn("успешно удалена", output)
        self.assertIn("Количество записей: 1", output)
        self.assertEqual(self.filepath.read_bytes(), original_metadata)
        self.assertEqual(table_data_path("users").read_bytes(), original_rows)
        save_schema.assert_not_called()
        save_rows.assert_not_called()
        remove_rows.assert_not_called()

    def test_confirmation_interrupts_cancel_and_cli_continues(self):
        for action in ("delete from users where ID=1", "drop_table users"):
            for interrupt in (EOFError, KeyboardInterrupt):
                with self.subTest(action=action, interrupt=interrupt):
                    self.seed_users(
                        [{"ID": 1, "name": "A", "age": 28, "is_active": True}]
                    )
                    status, output = self.run_commands(
                        [action, "info users", "exit"], answers=[interrupt]
                    )
                    self.assertEqual(status, 0)
                    self.assertIn("Операция отменена.", output)
                    self.assertIn("Количество записей: 1", output)
                    self.assertIn("users", load_metadata(self.filepath))
                    self.assertNotIn("успешно удалена", output)

    def test_missing_tables_invalid_conditions_and_no_matches_do_not_prompt(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        status, output = self.run_commands(
            [
                "drop_table missing",
                "delete from missing where ID=1",
                "delete from users where missing=1",
                "delete from users where ID=true",
                "delete from users where ID=100",
                "exit",
            ],
            answers=[],
        )
        self.assertEqual(status, 0)
        self.confirmation.assert_not_called()
        self.assertIn("Подходящие записи не найдены.", output)
        self.assertEqual(len(load_table_data("users")), 1)

    def test_one_confirmation_deletes_all_matching_rows(self):
        self.seed_users(
            [
                {"ID": 1, "name": "A", "age": 28, "is_active": True},
                {"ID": 2, "name": "B", "age": 28, "is_active": False},
            ]
        )
        status, output = self.run_commands(
            ["delete from users where age=28", "exit"], answers=["y"]
        )
        self.assertEqual(status, 0)
        self.confirmation.assert_called_once()
        self.assertEqual(output.count("успешно удалена из таблицы"), 2)
        self.assertEqual(load_table_data("users"), [])

    def test_confirmed_drop_of_empty_table_removes_both_files(self):
        self.seed_users()
        status, output = self.run_commands(["drop_table users", "exit"], answers=["y"])
        self.assertEqual(status, 0)
        self.confirmation.assert_called_once()
        self.assertIn('Таблица "users" успешно удалена.', output)
        self.assertEqual(load_metadata(self.filepath), {})
        self.assertFalse(table_data_path("users").exists())

    def test_handled_none_results_never_save_or_print_success(self):
        actions = {
            "create_table": "create_table new ID:int",
            "drop_table": "drop_table users",
            "insert": 'insert into users values ("B", 30, false)',
            "select": "select from users",
            "update": "update users set age=29 where ID=1",
            "delete": "delete from users where ID=1",
        }
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        for operation, command in actions.items():
            with (
                self.subTest(operation=operation),
                patch(f"primitive_db.engine.{operation}", return_value=None),
                patch("primitive_db.engine.save_metadata") as save_schema,
                patch("primitive_db.engine.save_table_data") as save_rows,
            ):
                status, output = self.run_commands([command, "info users", "exit"])
            self.assertEqual(status, 0)
            self.assertNotIn("успешно", output)
            self.assertIn("Количество записей: 1", output)
            save_schema.assert_not_called()
            save_rows.assert_not_called()

    def test_internal_filtering_is_neither_timed_nor_cached(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        status, output = self.run_commands(
            [
                'insert into users values ("B", 30, false)',
                "update users set age=29 where ID=1",
                "delete from users where ID=2",
                "exit",
            ]
        )
        self.assertEqual(status, 0)
        self.assertEqual(output.count("Функция insert выполнилась"), 1)
        self.assertNotIn("Функция select", output)
        self.assertNotIn("Результат получен из кэша.", output)

    def test_successful_writes_clear_cached_queries(self):
        for command in (
            "create_table other ID:int",
            "drop_table other",
            'insert into users values ("B", 30, false)',
            "update users set age=29 where ID=1",
            "delete from users where ID=1",
        ):
            with self.subTest(command=command):
                self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
                if command == "drop_table other":
                    metadata = load_metadata(self.filepath)
                    metadata["other"] = ["ID:int"]
                    save_metadata(self.filepath, metadata)
                    save_table_data("other", [])
                with patch(
                    "primitive_db.engine.clear_select_cache", wraps=clear_select_cache
                ) as clear:
                    status, output = self.run_commands(
                        [
                            "select from users",
                            "select from users",
                            command,
                            "select from users",
                            "exit",
                        ]
                    )
                self.assertEqual(status, 0)
                self.assertEqual(clear.call_count, 2)
                self.assertEqual(output.count("Результат получен из кэша."), 1)

    def test_cancellations_errors_and_noops_preserve_cache(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        with patch(
            "primitive_db.engine.clear_select_cache", wraps=clear_select_cache
        ) as clear:
            status, output = self.run_commands(
                [
                    "select from users",
                    "select from users",
                    "delete from users where ID=1",
                    "drop_table users",
                    'insert into users values ("B", "30", false)',
                    "update users set age=28 where ID=1",
                    "delete from users where ID=100",
                    "create_table users ID:int",
                    "select from users",
                    "exit",
                ],
                answers=["n", "n"],
            )
        self.assertEqual(status, 0)
        clear.assert_called_once()
        self.assertEqual(output.count("Результат получен из кэша."), 2)
        self.assertEqual(self.confirmation.call_count, 2)

    def test_failed_write_does_not_clear_cached_results(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        with (
            patch(
                "primitive_db.engine.clear_select_cache", wraps=clear_select_cache
            ) as clear,
            patch(
                "primitive_db.engine.save_table_data", side_effect=OSError("disk full")
            ),
        ):
            status, output = self.run_commands(
                ["select from users", 'insert into users values ("B", 30, false)']
            )
        self.assertEqual(status, 1)
        clear.assert_called_once()
        self.assertNotIn("успешно добавлена", output)

    def test_external_row_changes_are_read_before_using_cache(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        commands = iter(["select from users", "select from users", "change", "exit"])

        def read_command(_):
            command = next(commands)
            if command == "change":
                save_table_data(
                    "users", [{"ID": 1, "name": "B", "age": 29, "is_active": False}]
                )
                return "select from users"
            return command

        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            status, output = self.run_commands(read_command)
        self.assertEqual(status, 0)
        self.assertEqual(output.count("Результат получен из кэша."), 1)
        self.assertEqual(compute.call_count, 2)
        self.assertEqual(compute.call_args.args[0][0]["name"], "B")

    def test_corrupt_file_cannot_be_hidden_by_a_cached_select(self):
        self.seed_users([{"ID": 1, "name": "A", "age": 28, "is_active": True}])
        commands = iter(["select from users", "select from users", "corrupt"])

        def read_command(_):
            command = next(commands)
            if command == "corrupt":
                table_data_path("users").write_text("{broken", encoding="utf-8")
                return "select from users"
            return command

        status, output = self.run_commands(read_command)
        self.assertEqual(status, 1)
        self.assertEqual(output.count("Результат получен из кэша."), 1)
        self.assertIn("не удалось загрузить данные таблицы", output)
        self.assertEqual(
            table_data_path("users").read_text(encoding="utf-8"), "{broken"
        )

    def test_new_cli_session_starts_with_empty_cache(self):
        self.seed_users()
        status, first_output = self.run_commands(
            ["select from users", "select from users", "exit"]
        )
        self.assertEqual(status, 0)
        self.assertIn("Результат получен из кэша.", first_output)
        status, second_output = self.run_commands(["select from users", "exit"])
        self.assertEqual(status, 0)
        self.assertNotIn("Результат получен из кэша.", second_output)


class EntrypointTests(unittest.TestCase):
    def test_crud_from_all_entrypoints_persists_across_processes(self):
        executable_directory = Path(sys.executable).parent
        for entrypoint in (
            [sys.executable, "-m", "primitive_db.main"],
            [str(executable_directory / "database")],
            [str(executable_directory / "project")],
        ):
            with (
                self.subTest(entrypoint=entrypoint),
                tempfile.TemporaryDirectory() as cwd,
            ):
                result = subprocess.run(
                    entrypoint,
                    input="create_table users name:str age:int is_active:bool\n"
                    'insert into users values ("Sergei", 28, true)\nexit\n',
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                result = subprocess.run(
                    entrypoint,
                    input="select from users\n"
                    'update users set age=29 where name="Sergei"\n'
                    "delete from users where ID=1\ny\ninfo users\nexit\n",
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertIn("Sergei", result.stdout)
                self.assertIn("Количество записей: 0", result.stdout)
                filepath = Path(cwd) / "data" / "users.json"
                self.assertEqual(json.loads(filepath.read_text(encoding="utf-8")), [])

    def test_entrypoints_have_identical_behavior_and_persist_after_restart(self):
        executable_directory = Path(sys.executable).parent
        entrypoints = [
            [sys.executable, "-m", "primitive_db.main"],
            [str(executable_directory / "database")],
            [str(executable_directory / "project")],
        ]
        outputs = []
        for entrypoint in entrypoints:
            with (
                self.subTest(entrypoint=entrypoint),
                tempfile.TemporaryDirectory() as cwd,
            ):
                result = subprocess.run(
                    entrypoint,
                    input="create_table users name:str\nexit\n",
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                outputs.append(result.stdout)
                result = subprocess.run(
                    entrypoint,
                    input="list_tables\ndrop_table users\ny\nexit\n",
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("- users\n", result.stdout)
                self.assertEqual(load_metadata(Path(cwd) / "db_meta.json"), {})
        self.assertTrue(all(output == outputs[0] for output in outputs))

    def test_imports_are_silent(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import primitive_db.main; import primitive_db.engine; "
                "import primitive_db.core; import primitive_db.utils",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
