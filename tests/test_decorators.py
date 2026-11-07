import inspect
import io
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from helpers import (
    assert_equal,
    assert_in,
    assert_is,
    assert_is_none,
    assert_is_not_none,
    build_suite,
    raises,
    scenario,
)

from primitive_db.decorators import (
    confirm_action,
    create_cacher,
    handle_db_errors,
    log_time,
)


def test_error_handler_exception_messages_and_none_return():
    """Verify error handler exception messages and none return."""
    cases = (
        (
            FileNotFoundError("missing"),
            "Ошибка: Файл данных не найден. Возможно, база данных не инициализирована.",
        ),
        (KeyError("users"), "Ошибка: Таблица или столбец 'users' не найден."),
        (ValueError("invalid"), "Ошибка валидации: invalid"),
        (PermissionError("denied"), "Ошибка хранения данных: denied"),
        (RuntimeError("unexpected"), "Произошла непредвиденная ошибка: unexpected"),
    )
    for error, expected in cases:
        with scenario(error=error):

            @handle_db_errors
            def operation():
                """Exercise the decorated operation in this scenario."""
                raise error

            output = io.StringIO()
            with redirect_stdout(output):
                assert_is_none(operation())
            assert_equal(output.getvalue(), expected + "\n")


def test_error_handler_successful_values_and_arguments_are_preserved():
    """Verify error handler successful values and arguments are preserved."""

    @handle_db_errors
    def operation(value, *, multiplier):
        """Exercise the decorated operation in this scenario."""
        return value * multiplier

    assert_equal(operation(3, multiplier=2), 6)
    for value in ([], {}, False, 0):
        identity = handle_db_errors(lambda result: result)
        assert_is(identity(value), value)


def test_error_handler_base_exceptions_are_not_swallowed():
    """Verify error handler base exceptions are not swallowed."""
    for error in (KeyboardInterrupt, SystemExit):

        @handle_db_errors
        def operation():
            """Exercise the decorated operation in this scenario."""
            raise error

        with scenario(error=error), raises(error):
            operation()


def test_confirmation_yes_calls_function_once_with_original_arguments():
    """Verify confirmation yes calls function once with original arguments."""
    for answer in ("y", " y "):
        calls = []

        @confirm_action("удаление таблицы")
        def operation(value, *, name):
            """Exercise the decorated operation in this scenario."""
            calls.append((value, name))
            return []

        with (
            scenario(answer=answer),
            patch("builtins.input", return_value=answer) as prompt,
        ):
            assert_equal(operation(3, name="users"), [])
        assert_equal(calls, [(3, "users")])
        prompt.assert_called_once_with(
            'Вы уверены, что хотите выполнить "удаление таблицы"? [y/n]: '
        )


def test_confirmation_other_answers_cancel_without_calling_function():
    """Verify confirmation other answers cancel without calling function."""
    for answer in ("n", "", "yes", "Y", "1"):
        calls = []

        @confirm_action("удаление записей")
        def operation():
            """Exercise the decorated operation in this scenario."""
            calls.append(True)

        output = io.StringIO()
        with (
            scenario(answer=answer),
            patch("builtins.input", return_value=answer),
            redirect_stdout(output),
        ):
            assert_is_none(operation())
        assert_equal(calls, [])
        assert_equal(output.getvalue(), "Операция отменена.\n")


def test_confirmation_eof_and_ctrl_c_cancel_without_calling_function():
    """Verify confirmation eof and ctrl c cancel without calling function."""
    for error in (EOFError, KeyboardInterrupt):
        calls = []

        @confirm_action("удаление записей")
        def operation():
            """Exercise the decorated operation in this scenario."""
            calls.append(True)

        output = io.StringIO()
        with (
            scenario(error=error),
            patch("builtins.input", side_effect=error),
            redirect_stdout(output),
        ):
            assert_is_none(operation())
        assert_equal(calls, [])
        assert_in("Операция отменена.", output.getvalue())


def test_timing_exact_format_and_result_preservation():
    """Verify timing exact format and result preservation."""

    @log_time
    def operation(value, *, count):
        """Exercise the decorated operation in this scenario."""
        return [value] * count

    output = io.StringIO()
    with (
        patch("primitive_db.decorators.time.monotonic", side_effect=[10, 10.1234]),
        redirect_stdout(output),
    ):
        assert_equal(operation("A", count=2), ["A", "A"])
    assert_equal(output.getvalue(), "Функция operation выполнилась за 0.123 секунд.\n")


def test_timing_failed_calls_do_not_print_successful_timing():
    """Verify timing failed calls do not print successful timing."""

    @handle_db_errors
    @log_time
    def operation():
        """Exercise the decorated operation in this scenario."""
        raise ValueError("invalid")

    output = io.StringIO()
    with (
        patch("primitive_db.decorators.time.monotonic", return_value=10) as clock,
        redirect_stdout(output),
    ):
        assert_is_none(operation())
    clock.assert_called_once()
    assert_equal(output.getvalue(), "Ошибка валидации: invalid\n")


def test_timing_all_decorators_preserve_function_metadata():
    """Verify timing all decorators preserve function metadata."""

    def original(value: int, *, count: int = 1) -> list:
        """Original documentation."""
        return [value] * count

    for decorate in (handle_db_errors, confirm_action("test"), log_time):
        with scenario(decorate=decorate):
            wrapped = decorate(original)
            assert_equal(wrapped.__name__, original.__name__)
            assert_equal(wrapped.__doc__, original.__doc__)
            assert_equal(wrapped.__annotations__, original.__annotations__)
            assert_equal(inspect.signature(wrapped), inspect.signature(original))
            assert_is(wrapped.__wrapped__, original)


def test_cacher_values_are_computed_once_including_falsy_results():
    """Verify cacher values are computed once including falsy results."""
    cache = create_cacher()
    output = io.StringIO()
    with redirect_stdout(output):
        for index, value in enumerate(([], {}, None, False, 0)):
            compute = Mock(return_value=value)
            assert_is(cache(index, compute), value)
            assert_is(cache(index, compute), value)
            compute.assert_called_once_with()
    assert_equal(output.getvalue().count("Результат получен из кэша."), 5)


def test_cacher_caches_have_independent_closures():
    """Verify cacher caches have independent closures."""
    first, second = (create_cacher(), create_cacher())
    assert_equal(first("key", lambda: 1), 1)
    assert_equal(second("key", lambda: 2), 2)
    assert_is_not_none(first.__closure__)


def test_cacher_exceptions_are_not_cached():
    """Verify cacher exceptions are not cached."""
    cache = create_cacher()
    compute = Mock(side_effect=[ValueError("retry"), ["ok"]])
    with raises(ValueError):
        cache("key", compute)
    assert_equal(cache("key", compute), ["ok"])
    with redirect_stdout(io.StringIO()):
        assert_equal(cache("key", compute), ["ok"])
    assert_equal(compute.call_count, 2)


def load_tests(loader, tests, pattern):
    """Register procedural checks with standard unittest discovery."""
    return build_suite(globals())
