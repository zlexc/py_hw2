"""Procedural fixtures and assertions for standard unittest discovery."""

import unittest
from contextlib import ExitStack, contextmanager
from functools import wraps


def with_fixture(factory):
    """Give each test isolated state and clean up even when assertions fail."""

    def decorate(func):
        """Bind one fixture factory to a procedural test."""

        @wraps(func)
        def wrapper():
            """Prepare resources, run the test, and release its resources."""
            with ExitStack() as stack:
                return func(factory(stack))

        return wrapper

    return decorate


def build_suite(namespace):
    """Expose module-level test functions to unittest without custom classes."""
    return unittest.TestSuite(
        unittest.FunctionTestCase(
            function, description=f"{namespace['__name__']}.{name}"
        )
        for name, function in sorted(namespace.items())
        if name.startswith("test_") and callable(function)
    )


@contextmanager
def scenario(**details):
    """Attach parameter values to failures in a table-driven test."""
    try:
        yield
    except Exception as error:
        error.add_note(f"Scenario: {details!r}")
        raise


@contextmanager
def raises(expected):
    """Require a particular exception while letting unexpected ones surface."""
    try:
        yield
    except expected:
        return
    raise AssertionError(f"Expected {expected.__name__} to be raised")


def assert_equal(actual, expected, message=None):
    """Compare values without evaluating either expression more than once."""
    assert actual == expected, message or f"{actual!r} != {expected!r}"


def assert_is(actual, expected, message=None):
    """Require object identity rather than equality."""
    assert actual is expected, message or f"{actual!r} is not {expected!r}"


def assert_is_none(actual, message=None):
    """Require an explicit None result, preserving the distinction from []."""
    assert actual is None, message or f"Expected None, got {actual!r}"


def assert_is_not_none(actual, message=None):
    """Require a value to be present."""
    assert actual is not None, message or "Expected a value other than None"


def assert_in(member, container, message=None):
    """Require membership in a sequence, mapping, or captured output."""
    assert member in container, message or f"{member!r} not found in {container!r}"


def assert_not_in(member, container, message=None):
    """Reject unexpected membership or output."""
    assert member not in container, message or f"Unexpected {member!r} in {container!r}"


def assert_true(actual, message=None):
    """Require a truthy condition."""
    assert actual, message or f"Expected a truthy value, got {actual!r}"


def assert_false(actual, message=None):
    """Require a falsy condition."""
    assert not actual, message or f"Expected a falsy value, got {actual!r}"
