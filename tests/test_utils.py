import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from primitive_db.schema import validate_table_data
from primitive_db.utils import (
    delete_table_data,
    load_metadata,
    load_table_data,
    save_metadata,
    save_table_data,
    table_data_path,
)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filepath = Path(self.directory.name) / "db_meta.json"

    def test_missing_file_returns_empty_dictionary_without_creating_a_file(self):
        self.assertEqual(load_metadata(self.filepath), {})
        self.assertFalse(self.filepath.exists())

    def test_round_trip_preserves_unicode_and_table_order(self):
        metadata = {
            "пользователи": ["ID:int", "имя:str", "активен:bool"],
            "products": ["ID:int", "price:int"],
        }
        save_metadata(self.filepath, metadata)
        self.assertEqual(load_metadata(self.filepath), metadata)
        self.assertEqual(list(load_metadata(self.filepath)), list(metadata))
        self.assertIn('  "пользователи": [', self.filepath.read_text(encoding="utf-8"))
        save_metadata(self.filepath, {})
        self.assertEqual(load_metadata(self.filepath), {})

    def test_invalid_json_is_not_treated_as_an_empty_database(self):
        self.filepath.write_text("{broken", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            load_metadata(self.filepath)
        self.assertEqual(self.filepath.read_text(encoding="utf-8"), "{broken")

    def test_invalid_schema_is_rejected(self):
        for metadata in (
            [],
            {"": ["ID:int"]},
            {"users": "ID:int"},
            {"users": []},
            {"users": ["name:str"]},
            {"users": ["ID:str"]},
            {"users": ["ID:int", "ID:int"]},
            {"users": ["ID:int", "name:str", "name:bool"]},
            {"users": ["ID:int", 1]},
        ):
            with self.subTest(metadata=metadata):
                self.filepath.write_text(json.dumps(metadata), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_metadata(self.filepath)

    def test_write_failure_preserves_existing_file_and_removes_temporary_file(self):
        original = {"users": ["ID:int"]}
        save_metadata(self.filepath, original)
        with patch("primitive_db.utils.json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_metadata(self.filepath, {})
        self.assertEqual(load_metadata(self.filepath), original)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.filepath])


class TableDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_dir = Path(self.directory.name) / "data"
        data_patch = patch("primitive_db.utils.DATA_DIR", self.data_dir)
        data_patch.start()
        self.addCleanup(data_patch.stop)

    def test_missing_data_is_empty_without_creating_directory(self):
        self.assertEqual(load_table_data("users"), [])
        self.assertFalse(self.data_dir.exists())

    def test_save_creates_directory_and_round_trips_unicode(self):
        rows = [{"ID": 1, "name": "Сергей"}]
        save_table_data("users", rows)
        self.assertTrue((self.data_dir / "users.json").exists())
        self.assertEqual(load_table_data("users"), rows)

    def test_filenames_cannot_escape_or_collide_on_case_insensitive_systems(self):
        names = ["users", "Users", "../users", "a/b", "a\\b", "%55sers", "a b", "люди"]
        paths = [table_data_path(name) for name in names]
        self.assertEqual(len({str(path).casefold() for path in paths}), len(names))
        self.assertTrue(all(path.parent == self.data_dir for path in paths))
        for index, name in enumerate(names):
            save_table_data(name, [{"ID": index + 1}])
        for index, name in enumerate(names):
            self.assertEqual(load_table_data(name), [{"ID": index + 1}])

    def test_invalid_json_and_wrong_container_are_preserved(self):
        self.data_dir.mkdir()
        filepath = table_data_path("users")
        for content in ("{broken", "{}", "[1]", "null"):
            with self.subTest(content=content):
                filepath.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_table_data("users")
                self.assertEqual(filepath.read_text(encoding="utf-8"), content)

    def test_invalid_rows_are_rejected_against_schema(self):
        for rows in (
            [{"ID": 1}],
            [{"ID": 1, "name": "A", "extra": True}],
            [{"ID": 1, "name": 28}],
            [{"ID": True, "name": "A"}],
            [{"ID": 0, "name": "A"}],
            [{"ID": -1, "name": "A"}],
            [{"ID": 1, "name": "A"}, {"ID": 1, "name": "B"}],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_table_data(["ID:int", "name:str"], rows)

    def test_write_failure_preserves_rows_and_removes_temporary_file(self):
        rows = [{"ID": 1}]
        save_table_data("users", rows)
        with patch("primitive_db.utils.json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_table_data("users", [])
        self.assertEqual(load_table_data("users"), rows)
        self.assertEqual(list(self.data_dir.iterdir()), [table_data_path("users")])

    def test_delete_is_idempotent_and_does_not_touch_other_tables(self):
        save_table_data("users", [{"ID": 1}])
        save_table_data("Users", [{"ID": 2}])
        delete_table_data("users")
        delete_table_data("users")
        self.assertFalse(table_data_path("users").exists())
        self.assertEqual(load_table_data("Users"), [{"ID": 2}])
