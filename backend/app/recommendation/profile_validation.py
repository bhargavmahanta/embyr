"""Exact structural comparison for reviewed production policy profiles."""
from __future__ import annotations


def exact_profile_equal(actual: object, expected: object) -> bool:
    """Reject changed values, keys, list ordering, or JSON scalar types."""
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(
            exact_profile_equal(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            exact_profile_equal(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected
