import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

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

    def run_commands(self, commands):
        output = io.StringIO()
        with (
            patch("primitive_db.engine.METADATA_FILE", self.filepath),
            patch(
                "primitive_db.engine.prompt.string", side_effect=[*commands, EOFError]
            ),
            redirect_stdout(output),
        ):
            status = run()
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
        self.assertIn('Ошибка: Таблица "users" уже существует.', output)
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
        self.assertEqual(output.count("Некорректное значение:"), 10)
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
                    "delete from users where ID=1\ninfo users\nexit\n",
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
                    input="list_tables\ndrop_table users\nexit\n",
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
