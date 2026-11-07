import copy
import io
import unittest
from contextlib import redirect_stdout

from primitive_db.core import create_table, drop_table


class TableTests(unittest.TestCase):
    def test_create_adds_id_without_changing_the_input_columns(self):
        metadata = {}
        columns = ["name:str", "age:int", "is_active:bool"]
        result = create_table(metadata, "users", columns)
        self.assertIs(result, metadata)
        self.assertEqual(metadata["users"], ["ID:int", *columns])
        self.assertEqual(columns, ["name:str", "age:int", "is_active:bool"])

    def test_explicit_id_is_first_and_appears_once(self):
        for columns in (["name:str", "ID:int"], ["ID:int"]):
            with self.subTest(columns=columns):
                metadata = {}
                create_table(metadata, "users", columns)
                self.assertEqual(metadata["users"][0], "ID:int")
                self.assertEqual(metadata["users"].count("ID:int"), 1)

    def test_invalid_columns_leave_all_metadata_unchanged(self):
        for columns in (
            [],
            ["age:float"],
            ["name"],
            ["name:str:bool"],
            [":str"],
            [" :str"],
            ["name:"],
            ["name:str", "name:int"],
            ["ID:str"],
            ["ID:int", "ID:int"],
            ["name:str", "age:float"],
        ):
            with self.subTest(columns=columns):
                metadata = {"existing": ["ID:int"]}
                original = copy.deepcopy(metadata)
                output = io.StringIO()
                with redirect_stdout(output):
                    result = create_table(metadata, "users", columns)
                self.assertIs(result, metadata)
                self.assertEqual(metadata, original)
                self.assertIn("Некорректное значение:", output.getvalue())

    def test_empty_table_names_are_rejected(self):
        for table_name in ("", "   "):
            with self.subTest(table_name=table_name):
                metadata = {}
                with redirect_stdout(io.StringIO()):
                    create_table(metadata, table_name, ["name:str"])
                self.assertEqual(metadata, {})

    def test_existing_table_is_not_overwritten(self):
        metadata = {"users": ["ID:int", "name:str"]}
        output = io.StringIO()
        with redirect_stdout(output):
            create_table(metadata, "users", ["age:int"])
        self.assertEqual(metadata["users"], ["ID:int", "name:str"])
        self.assertEqual(output.getvalue(), 'Ошибка: Таблица "users" уже существует.\n')

    def test_names_are_case_sensitive(self):
        metadata = {}
        create_table(metadata, "users", ["name:str", "Name:str", "id:bool"])
        create_table(metadata, "Users", ["ID:int"])
        self.assertEqual(list(metadata), ["users", "Users"])
        self.assertEqual(
            metadata["users"], ["ID:int", "name:str", "Name:str", "id:bool"]
        )

    def test_drop_returns_updated_metadata(self):
        metadata = {"users": ["ID:int"], "products": ["ID:int"]}
        self.assertIs(drop_table(metadata, "users"), metadata)
        self.assertEqual(metadata, {"products": ["ID:int"]})

    def test_dropping_missing_table_preserves_metadata(self):
        metadata = {"users": ["ID:int"]}
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertIs(drop_table(metadata, "products"), metadata)
        self.assertEqual(metadata, {"users": ["ID:int"]})
        self.assertEqual(
            output.getvalue(), 'Ошибка: Таблица "products" не существует.\n'
        )
