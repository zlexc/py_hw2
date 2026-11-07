import unittest

from primitive_db.parser import parse_command, parse_set, parse_values, parse_where


class ParserTests(unittest.TestCase):
    def test_literals_keep_exact_types(self):
        values = parse_values('("28", 28, -2, +3, true, false, "", \'Привет\')')
        self.assertEqual(values, ["28", 28, -2, 3, True, False, "", "Привет"])
        self.assertEqual(
            [type(value) for value in values],
            [str, int, int, int, bool, bool, str, str],
        )

    def test_quoted_punctuation_and_keywords_are_data(self):
        self.assertEqual(
            parse_values('("A, B (where = set)", "select from users", "#")'),
            ["A, B (where = set)", "select from users", "#"],
        )

    def test_quotes_and_backslashes_can_be_escaped(self):
        self.assertEqual(
            parse_values(r"""("He said \"Hi\"", 'it\'s', "C:\\tmp")"""),
            ['He said "Hi"', "it's", "C:\\tmp"],
        )

    def test_empty_values_are_allowed_for_id_only_tables(self):
        self.assertEqual(parse_values("( )"), [])

    def test_invalid_values_are_rejected(self):
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
            r'("bad\q")',
            "(1) extra",
            "(__import__('os'))",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_values(text)

    def test_conditions_and_assignments_are_typed(self):
        self.assertEqual(parse_where("age=28"), {"age": 28})
        self.assertEqual(parse_where('name = "28"'), {"name": "28"})
        self.assertEqual(parse_set("is_active=false"), {"is_active": False})
        self.assertEqual(parse_set('"full name" = "A, B"'), {"full name": "A, B"})

    def test_only_one_equality_or_assignment_is_supported(self):
        for parse in (parse_where, parse_set):
            for text in (
                "age > 28",
                "age == 28",
                "age=28 and ID=1",
                "age=29, name='A'",
            ):
                with (
                    self.subTest(parse=parse, text=text),
                    self.assertRaises(ValueError),
                ):
                    parse(text)

    def test_complete_commands(self):
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
            with self.subTest(text=text):
                self.assertEqual(parse_command(text), expected)

    def test_quoted_table_and_column_names(self):
        parsed = parse_command(
            r"""update "active users" set "full name"='it\'s' where ID=1"""
        )
        self.assertEqual(parsed["table_name"], "active users")
        self.assertEqual(parsed["set_clause"], {"full name": "it's"})

    def test_invalid_complete_commands(self):
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
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_command(text)
