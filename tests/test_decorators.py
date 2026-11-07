import inspect
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from primitive_db.decorators import (
    confirm_action,
    create_cacher,
    handle_db_errors,
    log_time,
)


class ErrorHandlerTests(unittest.TestCase):
    def test_exception_messages_and_none_return(self):
        cases = (
            (
                FileNotFoundError("missing"),
                "Ошибка: Файл данных не найден. "
                "Возможно, база данных не инициализирована.",
            ),
            (KeyError("users"), "Ошибка: Таблица или столбец 'users' не найден."),
            (ValueError("invalid"), "Ошибка валидации: invalid"),
            (PermissionError("denied"), "Ошибка хранения данных: denied"),
            (RuntimeError("unexpected"), "Произошла непредвиденная ошибка: unexpected"),
        )
        for error, expected in cases:
            with self.subTest(error=error):

                @handle_db_errors
                def operation():
                    raise error

                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertIsNone(operation())
                self.assertEqual(output.getvalue(), expected + "\n")

    def test_successful_values_and_arguments_are_preserved(self):
        @handle_db_errors
        def operation(value, *, multiplier):
            return value * multiplier

        self.assertEqual(operation(3, multiplier=2), 6)
        for value in ([], {}, False, 0):
            identity = handle_db_errors(lambda result: result)
            self.assertIs(identity(value), value)

    def test_base_exceptions_are_not_swallowed(self):
        for error in (KeyboardInterrupt, SystemExit):

            @handle_db_errors
            def operation():
                raise error

            with self.subTest(error=error), self.assertRaises(error):
                operation()


class ConfirmationTests(unittest.TestCase):
    def test_yes_calls_function_once_with_original_arguments(self):
        for answer in ("y", " y "):
            calls = []

            @confirm_action("удаление таблицы")
            def operation(value, *, name):
                calls.append((value, name))
                return []

            with (
                self.subTest(answer=answer),
                patch("builtins.input", return_value=answer) as prompt,
            ):
                self.assertEqual(operation(3, name="users"), [])
            self.assertEqual(calls, [(3, "users")])
            prompt.assert_called_once_with(
                'Вы уверены, что хотите выполнить "удаление таблицы"? [y/n]: '
            )

    def test_other_answers_cancel_without_calling_function(self):
        for answer in ("n", "", "yes", "Y", "1"):
            calls = []

            @confirm_action("удаление записей")
            def operation():
                calls.append(True)

            output = io.StringIO()
            with (
                self.subTest(answer=answer),
                patch("builtins.input", return_value=answer),
                redirect_stdout(output),
            ):
                self.assertIsNone(operation())
            self.assertEqual(calls, [])
            self.assertEqual(output.getvalue(), "Операция отменена.\n")

    def test_eof_and_ctrl_c_cancel_without_calling_function(self):
        for error in (EOFError, KeyboardInterrupt):
            calls = []

            @confirm_action("удаление записей")
            def operation():
                calls.append(True)

            output = io.StringIO()
            with (
                self.subTest(error=error),
                patch("builtins.input", side_effect=error),
                redirect_stdout(output),
            ):
                self.assertIsNone(operation())
            self.assertEqual(calls, [])
            self.assertIn("Операция отменена.", output.getvalue())


class TimingTests(unittest.TestCase):
    def test_exact_format_and_result_preservation(self):
        @log_time
        def operation(value, *, count):
            return [value] * count

        output = io.StringIO()
        with (
            patch("primitive_db.decorators.time.monotonic", side_effect=[10, 10.1234]),
            redirect_stdout(output),
        ):
            self.assertEqual(operation("A", count=2), ["A", "A"])
        self.assertEqual(
            output.getvalue(), "Функция operation выполнилась за 0.123 секунд.\n"
        )

    def test_failed_calls_do_not_print_successful_timing(self):
        @handle_db_errors
        @log_time
        def operation():
            raise ValueError("invalid")

        output = io.StringIO()
        with (
            patch("primitive_db.decorators.time.monotonic", return_value=10) as clock,
            redirect_stdout(output),
        ):
            self.assertIsNone(operation())
        clock.assert_called_once()
        self.assertEqual(output.getvalue(), "Ошибка валидации: invalid\n")

    def test_all_decorators_preserve_function_metadata(self):
        def original(value: int, *, count: int = 1) -> list:
            """Original documentation."""
            return [value] * count

        for decorate in (handle_db_errors, confirm_action("test"), log_time):
            with self.subTest(decorate=decorate):
                wrapped = decorate(original)
                self.assertEqual(wrapped.__name__, original.__name__)
                self.assertEqual(wrapped.__doc__, original.__doc__)
                self.assertEqual(wrapped.__annotations__, original.__annotations__)
                self.assertEqual(
                    inspect.signature(wrapped), inspect.signature(original)
                )
                self.assertIs(wrapped.__wrapped__, original)


class CacherTests(unittest.TestCase):
    def test_values_are_computed_once_including_falsy_results(self):
        cache = create_cacher()
        output = io.StringIO()
        with redirect_stdout(output):
            for index, value in enumerate(([], {}, None, False, 0)):
                compute = Mock(return_value=value)
                self.assertIs(cache(index, compute), value)
                self.assertIs(cache(index, compute), value)
                compute.assert_called_once_with()
        self.assertEqual(output.getvalue().count("Результат получен из кэша."), 5)

    def test_caches_have_independent_closures(self):
        first, second = create_cacher(), create_cacher()
        self.assertEqual(first("key", lambda: 1), 1)
        self.assertEqual(second("key", lambda: 2), 2)
        self.assertIsNotNone(first.__closure__)

    def test_exceptions_are_not_cached(self):
        cache = create_cacher()
        compute = Mock(side_effect=[ValueError("retry"), ["ok"]])
        with self.assertRaises(ValueError):
            cache("key", compute)
        self.assertEqual(cache("key", compute), ["ok"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cache("key", compute), ["ok"])
        self.assertEqual(compute.call_count, 2)
