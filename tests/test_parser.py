from helpers import assert_equal, build_suite, raises, scenario

from primitive_db.parser import parse_command, parse_set, parse_values, parse_where


def test_parser_literals_keep_exact_types():
    """Verify parser literals keep exact types."""
    values = parse_values('("28", 28, -2, +3, true, false, "", \'Привет\')')
    assert_equal(values, ["28", 28, -2, 3, True, False, "", "Привет"])
    assert_equal(
        [type(value) for value in values], [str, int, int, int, bool, bool, str, str]
    )


def test_parser_quoted_punctuation_and_keywords_are_data():
    """Verify parser quoted punctuation and keywords are data."""
    assert_equal(
        parse_values('("A, B (where = set)", "select from users", "#")'),
        ["A, B (where = set)", "select from users", "#"],
    )


def test_parser_quotes_and_backslashes_can_be_escaped():
    """Verify parser quotes and backslashes can be escaped."""
    assert_equal(
        parse_values('("He said \\"Hi\\"", \'it\\\'s\', "C:\\\\tmp")'),
        ['He said "Hi"', "it's", "C:\\tmp"],
    )


def test_parser_empty_values_are_allowed_for_id_only_tables():
    """Verify parser empty values are allowed for id only tables."""
    assert_equal(parse_values("( )"), [])


def test_parser_invalid_values_are_rejected():
    """Verify parser invalid values are rejected."""
    for text in (
        "1, 2",
        "(1,)",
        "(,1)",
        "(1,,2)",
        '("a" "b")',
        "(Sergei)",
        "(True)",
        "(null)",
        "(1.5)",
        "(1 + 2)",
        '("unclosed)',
        "('unclosed)",
        '("bad\\q")',
        "(1) extra",
        "(__import__('os'))",
    ):
        with scenario(text=text), raises(ValueError):
            parse_values(text)


def test_parser_conditions_and_assignments_are_typed():
    """Verify parser conditions and assignments are typed."""
    assert_equal(parse_where("age=28"), {"age": 28})
    assert_equal(parse_where('name = "28"'), {"name": "28"})
    assert_equal(parse_set("is_active=false"), {"is_active": False})
    assert_equal(parse_set('"full name" = "A, B"'), {"full name": "A, B"})


def test_parser_only_one_equality_or_assignment_is_supported():
    """Verify parser only one equality or assignment is supported."""
    for parse in (parse_where, parse_set):
        for text in ("age > 28", "age == 28", "age=28 and ID=1", "age=29, name='A'"):
            with scenario(parse=parse, text=text), raises(ValueError):
                parse(text)


def test_parser_complete_commands():
    """Verify parser complete commands."""
    commands = {
        'insert into users values ("Sergei", 28, true)': {
            "command": "insert",
            "table_name": "users",
            "values": ["Sergei", 28, True],
        },
        "select from users": {
            "command": "select",
            "table_name": "users",
            "where_clause": None,
        },
        "select from users where age=28": {
            "command": "select",
            "table_name": "users",
            "where_clause": {"age": 28},
        },
        'update users set age=29 where name="Sergei"': {
            "command": "update",
            "table_name": "users",
            "set_clause": {"age": 29},
            "where_clause": {"name": "Sergei"},
        },
        "delete from users where ID=1": {
            "command": "delete",
            "table_name": "users",
            "where_clause": {"ID": 1},
        },
        "info users": {"command": "info", "table_name": "users"},
    }
    for text, expected in commands.items():
        with scenario(text=text):
            assert_equal(parse_command(text), expected)


def test_parser_quoted_table_and_column_names():
    """Verify parser quoted table and column names."""
    parsed = parse_command(
        'update "active users" set "full name"=\'it\\\'s\' where ID=1'
    )
    assert_equal(parsed["table_name"], "active users")
    assert_equal(parsed["set_clause"], {"full name": "it's"})


def test_parser_invalid_complete_commands():
    """Verify parser invalid complete commands."""
    for text in (
        "",
        "insert users values (1)",
        "insert into users (1)",
        "insert into users values (1) extra",
        "select from users where",
        "select from users extra",
        "update users set age=29",
        "update users set age=29, name='A' where ID=1",
        "delete from users",
        "delete from users where ID > 1",
        "info users extra",
        'info ""',
    ):
        with scenario(text=text), raises(ValueError):
            parse_command(text)


def load_tests(loader, tests, pattern):
    """Register procedural checks with standard unittest discovery."""
    return build_suite(globals())
