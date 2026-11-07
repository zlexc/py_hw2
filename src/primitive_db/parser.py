import ast
import re
import warnings

_TOKEN = re.compile(
    r"""\s+|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[(),=]|[^\s(),="'\\]+"""
)
_INTEGER = re.compile(r"[+-]?[0-9]+")


def _tokenize(text):
    """Split syntax outside quoted strings without discarding quotation marks."""
    tokens = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise ValueError(text)
        token = match.group()
        if not token.isspace():
            tokens.append(token)
        position = match.end()
    return tokens


def _string(token):
    """Decode a quoted string literal and reject invalid escapes."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            value = ast.literal_eval(token)
    except (SyntaxError, ValueError, SyntaxWarning) as error:
        raise ValueError(token) from error
    if not isinstance(value, str):
        raise ValueError(token)
    return value


def _identifier(token):
    """Read a nonempty identifier, allowing quoted names with spaces."""
    value = _string(token) if token.startswith(('"', "'")) else token
    if not value.strip() or token in {"(", ")", ",", "="}:
        raise ValueError(token)
    return value


def _value(token):
    """Parse a quoted string, signed integer, or lowercase boolean literal."""
    if token.startswith(('"', "'")):
        return _string(token)
    if _INTEGER.fullmatch(token):
        return int(token)
    if token in {"true", "false"}:
        return token == "true"
    raise ValueError(token)


def _values(tokens):
    """Read alternating values and commas inside a pair of parentheses."""
    if len(tokens) < 2 or tokens[0] != "(" or tokens[-1] != ")":
        raise ValueError("значения должны быть в круглых скобках")
    contents = tokens[1:-1]
    if not contents:
        return []
    if len(contents) % 2 == 0 or any(token != "," for token in contents[1::2]):
        raise ValueError("значения должны быть разделены запятыми")
    return [_value(token) for token in contents[::2]]


def parse_values(text):
    """Parse a parenthesized, comma-separated list of typed literals."""
    return _values(_tokenize(text))


def _clause(tokens):
    """Read the three tokens of a single column = literal expression."""
    if len(tokens) != 3 or tokens[1] != "=":
        raise ValueError("требуется одно выражение столбец = значение")
    return {_identifier(tokens[0]): _value(tokens[2])}


def parse_where(text):
    """Parse exactly one typed equality condition."""
    return _clause(_tokenize(text))


def parse_set(text):
    """Parse exactly one typed assignment."""
    return _clause(_tokenize(text))


def parse_command(text):
    """Parse a complete CRUD command, keeping quoted values distinct."""
    tokens = _tokenize(text)
    if not tokens:
        raise ValueError(text)
    command = tokens[0]

    if command == "insert" and len(tokens) >= 6:
        # insert into TABLE values (...): values begin at index 4.
        if tokens[1] == "into" and tokens[3] == "values":
            return {
                "command": command,
                "table_name": _identifier(tokens[2]),
                "values": _values(tokens[4:]),
            }
    elif command == "select" and len(tokens) in {3, 7}:
        # select from TABLE optionally followed by where COLUMN = VALUE.
        if tokens[1] == "from" and (len(tokens) == 3 or tokens[3] == "where"):
            return {
                "command": command,
                "table_name": _identifier(tokens[2]),
                "where_clause": _clause(tokens[4:]) if len(tokens) == 7 else None,
            }
    elif command == "update" and len(tokens) == 10:
        # update TABLE set COLUMN = VALUE where COLUMN = VALUE.
        # SET occupies tokens 3:6 and WHERE occupies tokens 7:10.
        if tokens[2] == "set" and tokens[6] == "where":
            return {
                "command": command,
                "table_name": _identifier(tokens[1]),
                "set_clause": _clause(tokens[3:6]),
                "where_clause": _clause(tokens[7:]),
            }
    elif command == "delete" and len(tokens) == 7:
        # delete from TABLE where COLUMN = VALUE: the clause starts at 4.
        if tokens[1] == "from" and tokens[3] == "where":
            return {
                "command": command,
                "table_name": _identifier(tokens[2]),
                "where_clause": _clause(tokens[4:]),
            }
    elif command == "info" and len(tokens) == 2:
        return {"command": command, "table_name": _identifier(tokens[1])}
    raise ValueError(text)
