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
from primitive_db.utils import load_metadata, save_metadata


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filepath = Path(self.directory.name) / "db_meta.json"

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


class EntrypointTests(unittest.TestCase):
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
