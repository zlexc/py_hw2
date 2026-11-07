import copy
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from helpers import (
    assert_equal,
    assert_in,
    assert_is,
    assert_is_none,
    assert_not_in,
    build_suite,
    with_fixture,
)

from primitive_db.core import clear_select_cache, matching_rows, select


def select_cache_fixture(stack):
    """Prepare isolated resources for select cache checks."""
    state = {}
    clear_select_cache()
    state["output"] = stack.enter_context(redirect_stdout(io.StringIO()))
    state["rows"] = [{"ID": 1, "name": "Sergei", "age": 28}]
    return state


@with_fixture(select_cache_fixture)
def test_select_cache_identical_snapshots_compute_only_once(state):
    """Verify select cache identical snapshots compute only once."""
    with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
        assert_equal(select(state["rows"], {"age": 28}), state["rows"])
        assert_equal(select(copy.deepcopy(state["rows"]), {"age": 28}), state["rows"])
    compute.assert_called_once()
    assert_equal(state["output"].getvalue().count("Результат получен из кэша."), 1)


@with_fixture(select_cache_fixture)
def test_select_cache_empty_results_are_cached(state):
    """Verify select cache empty results are cached."""
    with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
        assert_equal(select(state["rows"], {"age": 100}), [])
        assert_equal(select(state["rows"], {"age": 100}), [])
    compute.assert_called_once()


@with_fixture(select_cache_fixture)
def test_select_cache_returned_rows_cannot_poison_the_cache(state):
    """Verify select cache returned rows cannot poison the cache."""
    first = select(state["rows"])
    first[0]["name"] = "Changed"
    first.append({"ID": 2})
    second = select(state["rows"])
    assert_equal(second, state["rows"])
    second[0]["age"] = 99
    assert_equal(select(state["rows"]), state["rows"])


@with_fixture(select_cache_fixture)
def test_select_cache_changed_rows_and_row_order_produce_new_results(state):
    """Verify select cache changed rows and row order produce new results."""
    with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
        assert_equal(select(state["rows"])[0]["age"], 28)
        state["rows"][0]["age"] = 29
        assert_equal(select(state["rows"])[0]["age"], 29)
        state["rows"].append({"ID": 2, "name": "Ann", "age": 30})
        assert_equal([row["ID"] for row in select(state["rows"])], [1, 2])
        assert_equal([row["ID"] for row in select(state["rows"][::-1])], [2, 1])
    assert_equal(compute.call_count, 4)


@with_fixture(select_cache_fixture)
def test_select_cache_condition_keys_distinguish_bool_int_and_string(state):
    """Verify select cache condition keys distinguish bool int and string."""
    with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
        assert_equal(select(state["rows"], {"ID": True}), [])
        assert_equal(select(state["rows"], {"ID": 1}), state["rows"])
        assert_equal(select(state["rows"], {"ID": "1"}), [])
    assert_equal(compute.call_count, 3)


@with_fixture(select_cache_fixture)
def test_select_cache_row_keys_distinguish_bool_int_and_string(state):
    """Verify select cache row keys distinguish bool int and string."""
    with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
        for value in (True, 1, "1"):
            rows = [{"ID": 1, "value": value}]
            result = select(rows)
            assert_is(type(result[0]["value"]), type(value))
    assert_equal(compute.call_count, 3)


@with_fixture(select_cache_fixture)
def test_select_cache_clear_releases_prior_results(state):
    """Verify select cache clear releases prior results."""
    with patch("primitive_db.core.matching_rows", wraps=matching_rows) as compute:
        select(state["rows"])
        clear_select_cache()
        select(state["rows"])
    assert_equal(compute.call_count, 2)
    assert_not_in("Результат получен из кэша.", state["output"].getvalue())


@with_fixture(select_cache_fixture)
def test_select_cache_computation_failure_is_handled_and_not_cached(state):
    """Verify select cache computation failure is handled and not cached."""
    with patch("primitive_db.core.matching_rows", side_effect=ValueError("retry")):
        assert_is_none(select(state["rows"]))
    assert_equal(select(state["rows"]), state["rows"])
    assert_equal(select(state["rows"]), state["rows"])
    assert_equal(state["output"].getvalue().count("Результат получен из кэша."), 1)
    assert_in("Ошибка валидации: retry", state["output"].getvalue())


@with_fixture(select_cache_fixture)
def test_select_cache_cache_hits_are_still_timed_with_the_public_function_name(state):
    """Verify select cache cache hits are still timed with the public function name."""
    with patch(
        "primitive_db.decorators.time.monotonic", side_effect=[10, 10.1, 20, 20.001]
    ):
        select(state["rows"])
        select(state["rows"])
    assert_in("Функция select выполнилась за 0.100 секунд.", state["output"].getvalue())
    assert_in("Функция select выполнилась за 0.001 секунд.", state["output"].getvalue())
    assert_not_in("Функция wrapper", state["output"].getvalue())


def load_tests(loader, tests, pattern):
    """Register procedural checks with standard unittest discovery."""
    return build_suite(globals())
