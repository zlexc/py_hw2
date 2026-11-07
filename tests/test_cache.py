import copy
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from primitive_db.core import clear_select_cache, matching_rows, select


class SelectCacheTests(unittest.TestCase):
    def setUp(self):
        clear_select_cache()
        self.output = self.enterContext(redirect_stdout(io.StringIO()))
        self.rows = [{"ID": 1, "name": "Sergei", "age": 28}]

    def test_identical_snapshots_compute_only_once(self):
        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            self.assertEqual(select(self.rows, {"age": 28}), self.rows)
            self.assertEqual(select(copy.deepcopy(self.rows), {"age": 28}), self.rows)
        compute.assert_called_once()
        self.assertEqual(self.output.getvalue().count("Результат получен из кэша."), 1)

    def test_empty_results_are_cached(self):
        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            self.assertEqual(select(self.rows, {"age": 100}), [])
            self.assertEqual(select(self.rows, {"age": 100}), [])
        compute.assert_called_once()

    def test_returned_rows_cannot_poison_the_cache(self):
        first = select(self.rows)
        first[0]["name"] = "Changed"
        first.append({"ID": 2})
        second = select(self.rows)
        self.assertEqual(second, self.rows)
        second[0]["age"] = 99
        self.assertEqual(select(self.rows), self.rows)

    def test_changed_rows_and_row_order_produce_new_results(self):
        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            self.assertEqual(select(self.rows)[0]["age"], 28)
            self.rows[0]["age"] = 29
            self.assertEqual(select(self.rows)[0]["age"], 29)
            self.rows.append({"ID": 2, "name": "Ann", "age": 30})
            self.assertEqual([row["ID"] for row in select(self.rows)], [1, 2])
            self.assertEqual([row["ID"] for row in select(self.rows[::-1])], [2, 1])
        self.assertEqual(compute.call_count, 4)

    def test_condition_keys_distinguish_bool_int_and_string(self):
        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            self.assertEqual(select(self.rows, {"ID": True}), [])
            self.assertEqual(select(self.rows, {"ID": 1}), self.rows)
            self.assertEqual(select(self.rows, {"ID": "1"}), [])
        self.assertEqual(compute.call_count, 3)

    def test_row_keys_distinguish_bool_int_and_string(self):
        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            for value in (True, 1, "1"):
                rows = [{"ID": 1, "value": value}]
                result = select(rows)
                self.assertIs(type(result[0]["value"]), type(value))
        self.assertEqual(compute.call_count, 3)

    def test_clear_releases_prior_results(self):
        with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
            select(self.rows)
            clear_select_cache()
            select(self.rows)
        self.assertEqual(compute.call_count, 2)
        self.assertNotIn("Результат получен из кэша.", self.output.getvalue())

    def test_computation_failure_is_handled_and_not_cached(self):
        with patch("primitive_db.core.matching_rows", side_effect=ValueError("retry")):
            self.assertIsNone(select(self.rows))
        self.assertEqual(select(self.rows), self.rows)
        self.assertEqual(select(self.rows), self.rows)
        self.assertEqual(self.output.getvalue().count("Результат получен из кэша."), 1)
        self.assertIn("Ошибка валидации: retry", self.output.getvalue())

    def test_cache_hits_are_still_timed_with_the_public_function_name(self):
        with patch(
            "primitive_db.decorators.time.monotonic", side_effect=[10, 10.1, 20, 20.001]
        ):
            select(self.rows)
            select(self.rows)
        self.assertIn(
            "Функция select выполнилась за 0.100 секунд.", self.output.getvalue()
        )
        self.assertIn(
            "Функция select выполнилась за 0.001 секунд.", self.output.getvalue()
        )
        self.assertNotIn("Функция wrapper", self.output.getvalue())
