import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from primitive_db.utils import load_metadata, save_metadata


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
