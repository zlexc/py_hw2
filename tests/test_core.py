import copy
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from primitive_db.core import (
    clear_select_cache,
    create_table,
    delete,
    drop_table,
    insert,
    select,
    update,
)


class TableTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("builtins.input", return_value="y"))

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
                self.assertIsNone(result)
                self.assertEqual(metadata, original)
                self.assertIn("Ошибка валидации:", output.getvalue())

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
        self.assertEqual(
            output.getvalue(), 'Ошибка валидации: Таблица "users" уже существует.\n'
        )

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
            self.assertIsNone(drop_table(metadata, "products"))
        self.assertEqual(metadata, {"users": ["ID:int"]})
        self.assertEqual(
            output.getvalue(), "Ошибка: Таблица или столбец 'products' не найден.\n"
        )


class CrudTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch("builtins.input", return_value="y"))
        self.enterContext(redirect_stdout(io.StringIO()))
        clear_select_cache()
        self.metadata = {"users": ["ID:int", "name:str", "age:int", "is_active:bool"]}
        self.rows = [
            {"ID": 1, "name": "Sergei", "age": 28, "is_active": True},
            {"ID": 3, "name": "Ann", "age": 28, "is_active": False},
        ]
        self.original = copy.deepcopy(self.rows)

    def test_insert_uses_max_id_and_does_not_mutate_input(self):
        result = insert(self.metadata, "users", ["Nina", -2, False], self.rows)
        self.assertEqual(
            result[-1], {"ID": 4, "name": "Nina", "age": -2, "is_active": False}
        )
        self.assertEqual(self.rows, self.original)

    def test_three_argument_insert_loads_existing_rows(self):
        with patch("primitive_db.core.load_table_data", return_value=self.rows) as load:
            result = insert(self.metadata, "users", ["Nina", 30, True])
        load.assert_called_once_with("users")
        self.assertEqual(result[-1]["ID"], 4)

    def test_empty_table_and_id_only_table(self):
        self.assertEqual(insert({"ids": ["ID:int"]}, "ids", [], []), [{"ID": 1}])
        result = insert(self.metadata, "users", ["", 0, False], [])
        self.assertEqual(result[-1]["ID"], 1)
        self.assertEqual(result[-1]["name"], "")

    def test_invalid_insert_values_do_not_change_rows(self):
        for values in (
            ["Sergei", "28", True],
            ["Sergei", True, True],
            ["Sergei", 28, 1],
            [28, 28, True],
            ["Sergei", 28],
            [1, "Sergei", 28, True],
            ["Sergei", None, True],
        ):
            with self.subTest(values=values):
                self.assertIsNone(insert(self.metadata, "users", values, self.rows))
            self.assertEqual(self.rows, self.original)

    def test_missing_table_is_rejected(self):
        self.assertIsNone(insert(self.metadata, "missing", [], []))

    def test_invalid_existing_rows_are_rejected(self):
        self.assertIsNone(
            insert(self.metadata, "users", ["Nina", 30, True], [{"ID": True}])
        )

    def test_select_all_and_exact_type_equality(self):
        result = select(self.rows)
        self.assertEqual(result, self.rows)
        result[0]["name"] = "Changed"
        self.assertEqual(self.rows, self.original)
        self.assertEqual(select(self.rows, {"ID": True}), [])
        self.assertEqual(select(self.rows, {"age": "28"}), [])
        self.assertEqual(select(self.rows, {"is_active": False}), [self.rows[1]])

    def test_update_changes_all_matches_without_mutation(self):
        result = update(self.rows, {"age": 29}, {"age": 28})
        self.assertEqual([row["age"] for row in result], [29, 29])
        self.assertEqual(self.rows, self.original)
        self.assertEqual(update(self.rows, {"age": 29}, {"ID": 100}), self.rows)

    def test_id_is_read_only(self):
        self.assertIsNone(update(self.rows, {"ID": 2}, {"ID": 1}))
        self.assertEqual(self.rows, self.original)

    def test_delete_changes_all_matches_without_mutation(self):
        self.assertEqual(delete(self.rows, {"age": 28}), [])
        self.assertEqual(delete(self.rows, {"ID": 1}), [self.rows[1]])
        self.assertEqual(delete(self.rows, {"ID": 100}), self.rows)
        self.assertEqual(self.rows, self.original)

    def test_id_generation_after_deletion_cannot_collide(self):
        remaining = delete(self.rows, {"ID": 1})
        result = insert(self.metadata, "users", ["Nina", 30, True], remaining)
        self.assertEqual(result[-1]["ID"], 4)
        remaining = delete(self.rows, {"ID": 3})
        result = insert(self.metadata, "users", ["Nina", 30, True], remaining)
        self.assertEqual(result[-1]["ID"], 2)
