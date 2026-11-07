import copy
import io
from contextlib import redirect_stdout
from unittest.mock import patch

from helpers import (
    assert_equal,
    assert_in,
    assert_is,
    assert_is_none,
    build_suite,
    scenario,
    with_fixture,
)

from primitive_db.core import (
    clear_select_cache,
    create_table,
    delete,
    drop_table,
    insert,
    select,
    update,
)


def table_fixture(stack):
    """Prepare isolated resources for table checks."""
    state = {}
    stack.enter_context(patch("builtins.input", return_value="y"))
    return state


@with_fixture(table_fixture)
def test_table_create_adds_id_without_changing_the_input_columns(state):
    """Verify table create adds id without changing the input columns."""
    metadata = {}
    columns = ["name:str", "age:int", "is_active:bool"]
    result = create_table(metadata, "users", columns)
    assert_is(result, metadata)
    assert_equal(metadata["users"], ["ID:int", *columns])
    assert_equal(columns, ["name:str", "age:int", "is_active:bool"])


@with_fixture(table_fixture)
def test_table_explicit_id_is_first_and_appears_once(state):
    """Verify table explicit id is first and appears once."""
    for columns in (["name:str", "ID:int"], ["ID:int"]):
        with scenario(columns=columns):
            metadata = {}
            create_table(metadata, "users", columns)
            assert_equal(metadata["users"][0], "ID:int")
            assert_equal(metadata["users"].count("ID:int"), 1)


@with_fixture(table_fixture)
def test_table_invalid_columns_leave_all_metadata_unchanged(state):
    """Verify table invalid columns leave all metadata unchanged."""
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
        with scenario(columns=columns):
            metadata = {"existing": ["ID:int"]}
            original = copy.deepcopy(metadata)
            output = io.StringIO()
            with redirect_stdout(output):
                result = create_table(metadata, "users", columns)
            assert_is_none(result)
            assert_equal(metadata, original)
            assert_in("Ошибка валидации:", output.getvalue())


@with_fixture(table_fixture)
def test_table_empty_table_names_are_rejected(state):
    """Verify table empty table names are rejected."""
    for table_name in ("", "   "):
        with scenario(table_name=table_name):
            metadata = {}
            with redirect_stdout(io.StringIO()):
                create_table(metadata, table_name, ["name:str"])
            assert_equal(metadata, {})


@with_fixture(table_fixture)
def test_table_existing_table_is_not_overwritten(state):
    """Verify table existing table is not overwritten."""
    metadata = {"users": ["ID:int", "name:str"]}
    output = io.StringIO()
    with redirect_stdout(output):
        create_table(metadata, "users", ["age:int"])
    assert_equal(metadata["users"], ["ID:int", "name:str"])
    assert_equal(
        output.getvalue(), 'Ошибка валидации: Таблица "users" уже существует.\n'
    )


@with_fixture(table_fixture)
def test_table_names_are_case_sensitive(state):
    """Verify table names are case sensitive."""
    metadata = {}
    create_table(metadata, "users", ["name:str", "Name:str", "id:bool"])
    create_table(metadata, "Users", ["ID:int"])
    assert_equal(list(metadata), ["users", "Users"])
    assert_equal(metadata["users"], ["ID:int", "name:str", "Name:str", "id:bool"])


@with_fixture(table_fixture)
def test_table_drop_returns_updated_metadata(state):
    """Verify table drop returns updated metadata."""
    metadata = {"users": ["ID:int"], "products": ["ID:int"]}
    assert_is(drop_table(metadata, "users"), metadata)
    assert_equal(metadata, {"products": ["ID:int"]})


@with_fixture(table_fixture)
def test_table_dropping_missing_table_preserves_metadata(state):
    """Verify table dropping missing table preserves metadata."""
    metadata = {"users": ["ID:int"]}
    output = io.StringIO()
    with redirect_stdout(output):
        assert_is_none(drop_table(metadata, "products"))
    assert_equal(metadata, {"users": ["ID:int"]})
    assert_equal(
        output.getvalue(), "Ошибка: Таблица или столбец 'products' не найден.\n"
    )


def crud_fixture(stack):
    """Prepare isolated resources for crud checks."""
    state = {}
    stack.enter_context(patch("builtins.input", return_value="y"))
    stack.enter_context(redirect_stdout(io.StringIO()))
    clear_select_cache()
    state["metadata"] = {"users": ["ID:int", "name:str", "age:int", "is_active:bool"]}
    state["rows"] = [
        {"ID": 1, "name": "Sergei", "age": 28, "is_active": True},
        {"ID": 3, "name": "Ann", "age": 28, "is_active": False},
    ]
    state["original"] = copy.deepcopy(state["rows"])
    return state


@with_fixture(crud_fixture)
def test_crud_insert_uses_max_id_and_does_not_mutate_input(state):
    """Verify crud insert uses max id and does not mutate input."""
    result = insert(state["metadata"], "users", ["Nina", -2, False], state["rows"])
    assert_equal(result[-1], {"ID": 4, "name": "Nina", "age": -2, "is_active": False})
    assert_equal(state["rows"], state["original"])


@with_fixture(crud_fixture)
def test_crud_three_argument_insert_loads_existing_rows(state):
    """Verify crud three argument insert loads existing rows."""
    with patch("primitive_db.core.load_table_data", return_value=state["rows"]) as load:
        result = insert(state["metadata"], "users", ["Nina", 30, True])
    load.assert_called_once_with("users")
    assert_equal(result[-1]["ID"], 4)


@with_fixture(crud_fixture)
def test_crud_empty_table_and_id_only_table(state):
    """Verify crud empty table and id only table."""
    assert_equal(insert({"ids": ["ID:int"]}, "ids", [], []), [{"ID": 1}])
    result = insert(state["metadata"], "users", ["", 0, False], [])
    assert_equal(result[-1]["ID"], 1)
    assert_equal(result[-1]["name"], "")


@with_fixture(crud_fixture)
def test_crud_invalid_insert_values_do_not_change_rows(state):
    """Verify crud invalid insert values do not change rows."""
    for values in (
        ["Sergei", "28", True],
        ["Sergei", True, True],
        ["Sergei", 28, 1],
        [28, 28, True],
        ["Sergei", 28],
        [1, "Sergei", 28, True],
        ["Sergei", None, True],
    ):
        with scenario(values=values):
            assert_is_none(insert(state["metadata"], "users", values, state["rows"]))
        assert_equal(state["rows"], state["original"])


@with_fixture(crud_fixture)
def test_crud_missing_table_is_rejected(state):
    """Verify crud missing table is rejected."""
    assert_is_none(insert(state["metadata"], "missing", [], []))


@with_fixture(crud_fixture)
def test_crud_invalid_existing_rows_are_rejected(state):
    """Verify crud invalid existing rows are rejected."""
    assert_is_none(
        insert(state["metadata"], "users", ["Nina", 30, True], [{"ID": True}])
    )


@with_fixture(crud_fixture)
def test_crud_select_all_and_exact_type_equality(state):
    """Verify crud select all and exact type equality."""
    result = select(state["rows"])
    assert_equal(result, state["rows"])
    result[0]["name"] = "Changed"
    assert_equal(state["rows"], state["original"])
    assert_equal(select(state["rows"], {"ID": True}), [])
    assert_equal(select(state["rows"], {"age": "28"}), [])
    assert_equal(select(state["rows"], {"is_active": False}), [state["rows"][1]])


@with_fixture(crud_fixture)
def test_crud_update_changes_all_matches_without_mutation(state):
    """Verify crud update changes all matches without mutation."""
    result = update(state["rows"], {"age": 29}, {"age": 28})
    assert_equal([row["age"] for row in result], [29, 29])
    assert_equal(state["rows"], state["original"])
    assert_equal(update(state["rows"], {"age": 29}, {"ID": 100}), state["rows"])


@with_fixture(crud_fixture)
def test_crud_id_is_read_only(state):
    """Verify crud id is read only."""
    assert_is_none(update(state["rows"], {"ID": 2}, {"ID": 1}))
    assert_equal(state["rows"], state["original"])


@with_fixture(crud_fixture)
def test_crud_delete_changes_all_matches_without_mutation(state):
    """Verify crud delete changes all matches without mutation."""
    assert_equal(delete(state["rows"], {"age": 28}), [])
    assert_equal(delete(state["rows"], {"ID": 1}), [state["rows"][1]])
    assert_equal(delete(state["rows"], {"ID": 100}), state["rows"])
    assert_equal(state["rows"], state["original"])


@with_fixture(crud_fixture)
def test_crud_id_generation_after_deletion_cannot_collide(state):
    """Verify crud id generation after deletion cannot collide."""
    remaining = delete(state["rows"], {"ID": 1})
    result = insert(state["metadata"], "users", ["Nina", 30, True], remaining)
    assert_equal(result[-1]["ID"], 4)
    remaining = delete(state["rows"], {"ID": 3})
    result = insert(state["metadata"], "users", ["Nina", 30, True], remaining)
    assert_equal(result[-1]["ID"], 2)


def load_tests(loader, tests, pattern):
    """Register procedural checks with standard unittest discovery."""
    return build_suite(globals())
