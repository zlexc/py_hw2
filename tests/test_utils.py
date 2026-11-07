import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from helpers import (
    assert_equal,
    assert_false,
    assert_in,
    assert_true,
    build_suite,
    raises,
    scenario,
    with_fixture,
)

from primitive_db.schema import validate_table_data
from primitive_db.utils import (
    delete_table_data,
    load_metadata,
    load_table_data,
    save_metadata,
    save_table_data,
    table_data_path,
)


def metadata_fixture(stack):
    """Prepare isolated resources for metadata checks."""
    state = {}
    state["directory"] = tempfile.TemporaryDirectory()
    stack.callback(state["directory"].cleanup)
    state["filepath"] = Path(state["directory"].name) / "db_meta.json"
    return state


@with_fixture(metadata_fixture)
def test_metadata_missing_file_returns_empty_dictionary_without_creating_a_file(state):
    """Verify metadata missing file returns empty dictionary without creating a file."""
    assert_equal(load_metadata(state["filepath"]), {})
    assert_false(state["filepath"].exists())


@with_fixture(metadata_fixture)
def test_metadata_round_trip_preserves_unicode_and_table_order(state):
    """Verify metadata round trip preserves unicode and table order."""
    metadata = {
        "пользователи": ["ID:int", "имя:str", "активен:bool"],
        "products": ["ID:int", "price:int"],
    }
    save_metadata(state["filepath"], metadata)
    assert_equal(load_metadata(state["filepath"]), metadata)
    assert_equal(list(load_metadata(state["filepath"])), list(metadata))
    assert_in('  "пользователи": [', state["filepath"].read_text(encoding="utf-8"))
    save_metadata(state["filepath"], {})
    assert_equal(load_metadata(state["filepath"]), {})


@with_fixture(metadata_fixture)
def test_metadata_invalid_json_is_not_treated_as_an_empty_database(state):
    """Verify metadata invalid json is not treated as an empty database."""
    state["filepath"].write_text("{broken", encoding="utf-8")
    with raises(json.JSONDecodeError):
        load_metadata(state["filepath"])
    assert_equal(state["filepath"].read_text(encoding="utf-8"), "{broken")


@with_fixture(metadata_fixture)
def test_metadata_invalid_schema_is_rejected(state):
    """Verify metadata invalid schema is rejected."""
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
        with scenario(metadata=metadata):
            state["filepath"].write_text(json.dumps(metadata), encoding="utf-8")
            with raises(ValueError):
                load_metadata(state["filepath"])


@with_fixture(metadata_fixture)
def test_metadata_write_failure_preserves_existing_file_and_removes_temporary_file(
    state,
):
    """Verify failed writes preserve metadata and clean up temporary files."""
    original = {"users": ["ID:int"]}
    save_metadata(state["filepath"], original)
    with patch("primitive_db.utils.json.dump", side_effect=OSError("disk full")):
        with raises(OSError):
            save_metadata(state["filepath"], {})
    assert_equal(load_metadata(state["filepath"]), original)
    assert_equal(list(Path(state["directory"].name).iterdir()), [state["filepath"]])


def table_data_fixture(stack):
    """Prepare isolated resources for table data checks."""
    state = {}
    state["directory"] = tempfile.TemporaryDirectory()
    stack.callback(state["directory"].cleanup)
    state["data_dir"] = Path(state["directory"].name) / "data"
    data_patch = patch("primitive_db.utils.DATA_DIR", state["data_dir"])
    data_patch.start()
    stack.callback(data_patch.stop)
    return state


@with_fixture(table_data_fixture)
def test_table_data_missing_data_is_empty_without_creating_directory(state):
    """Verify table data missing data is empty without creating directory."""
    assert_equal(load_table_data("users"), [])
    assert_false(state["data_dir"].exists())


@with_fixture(table_data_fixture)
def test_table_data_save_creates_directory_and_round_trips_unicode(state):
    """Verify table data save creates directory and round trips unicode."""
    rows = [{"ID": 1, "name": "Сергей"}]
    save_table_data("users", rows)
    assert_true((state["data_dir"] / "users.json").exists())
    assert_equal(load_table_data("users"), rows)


@with_fixture(table_data_fixture)
def test_table_data_filenames_cannot_escape_or_collide_on_case_insensitive_systems(
    state,
):
    """Verify table filenames stay contained and distinct regardless of case."""
    names = ["users", "Users", "../users", "a/b", "a\\b", "%55sers", "a b", "люди"]
    paths = [table_data_path(name) for name in names]
    assert_equal(len({str(path).casefold() for path in paths}), len(names))
    assert_true(all((path.parent == state["data_dir"] for path in paths)))
    for index, name in enumerate(names):
        save_table_data(name, [{"ID": index + 1}])
    for index, name in enumerate(names):
        assert_equal(load_table_data(name), [{"ID": index + 1}])


@with_fixture(table_data_fixture)
def test_table_data_invalid_json_and_wrong_container_are_preserved(state):
    """Verify table data invalid json and wrong container are preserved."""
    state["data_dir"].mkdir()
    filepath = table_data_path("users")
    for content in ("{broken", "{}", "[1]", "null"):
        with scenario(content=content):
            filepath.write_text(content, encoding="utf-8")
            with raises(ValueError):
                load_table_data("users")
            assert_equal(filepath.read_text(encoding="utf-8"), content)


@with_fixture(table_data_fixture)
def test_table_data_invalid_rows_are_rejected_against_schema(state):
    """Verify table data invalid rows are rejected against schema."""
    for rows in (
        [{"ID": 1}],
        [{"ID": 1, "name": "A", "extra": True}],
        [{"ID": 1, "name": 28}],
        [{"ID": True, "name": "A"}],
        [{"ID": 0, "name": "A"}],
        [{"ID": -1, "name": "A"}],
        [{"ID": 1, "name": "A"}, {"ID": 1, "name": "B"}],
    ):
        with scenario(rows=rows), raises(ValueError):
            validate_table_data(["ID:int", "name:str"], rows)


@with_fixture(table_data_fixture)
def test_table_data_write_failure_preserves_rows_and_removes_temporary_file(state):
    """Verify table data write failure preserves rows and removes temporary file."""
    rows = [{"ID": 1}]
    save_table_data("users", rows)
    with patch("primitive_db.utils.json.dump", side_effect=OSError("disk full")):
        with raises(OSError):
            save_table_data("users", [])
    assert_equal(load_table_data("users"), rows)
    assert_equal(list(state["data_dir"].iterdir()), [table_data_path("users")])


@with_fixture(table_data_fixture)
def test_table_data_delete_is_idempotent_and_does_not_touch_other_tables(state):
    """Verify table data delete is idempotent and does not touch other tables."""
    save_table_data("users", [{"ID": 1}])
    save_table_data("Users", [{"ID": 2}])
    delete_table_data("users")
    delete_table_data("users")
    assert_false(table_data_path("users").exists())
    assert_equal(load_table_data("Users"), [{"ID": 2}])


def load_tests(loader, tests, pattern):
    """Register procedural checks with standard unittest discovery."""
    return build_suite(globals())
