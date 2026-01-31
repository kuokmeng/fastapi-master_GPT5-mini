import pytest

from fastapi.utils import build_from_pydantic_error


def test_empty_loc_returns_empty_pointer():
    assert build_from_pydantic_error(()) == ""
    assert build_from_pydantic_error([]) == ""


def test_body_marker_only_returns_empty_pointer():
    assert build_from_pydantic_error(("body",)) == ""


def test_simple_path_segments():
    assert build_from_pydantic_error(("body", "user", "name")) == "/user/name"


def test_numeric_indexes_are_stringified():
    assert build_from_pydantic_error(("body", "items", 0, "id")) == "/items/0/id"


def test_escape_tilde_and_slash():
    # '~' -> '~0', '/' -> '~1'
    result = build_from_pydantic_error(("body", "a~b", "c/d"))
    assert result == "/a~0b/c~1d"
    # ensure there is no literal '/' inside an escaped segment
    assert "c/d" not in result


def test_non_str_segments_are_stringified_safely():
    result = build_from_pydantic_error(("json", 123, None, True))
    assert result == "/123/None/True"


def test_no_src_marker_still_builds_pointer():
    assert build_from_pydantic_error(("user", "name")) == "/user/name"


def test_security_characters_are_escaped_and_no_raw_parent_traversal():
    suspicious = "..\\/../etc/passwd"  # contains backslashes and slashes
    pointer = build_from_pydantic_error(("body", suspicious))
    # No literal '../' or '..\/' should remain that could be misinterpreted
    assert r"..\/.." not in pointer
    assert "../" not in pointer
    # slashes inside the segment must be escaped
    assert "/..\\/../etc/passwd" not in pointer


def test_concurrent_invocations_are_safe():
    # Ensure multiple concurrent calls don't mutate shared state or raise
    from concurrent.futures import ThreadPoolExecutor

    locs = [("body", "a/b", i) for i in range(50)]

    def call(l):
        return build_from_pydantic_error(l)

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(call, locs))

    # Basic sanity checks
    assert len(results) == len(locs)
    for i, res in enumerate(results):
        assert res.endswith(f"/{i}")


def test_long_pointer_truncation_and_suffix():
    # Build many long segments to exceed the internal MAX_POINTER_LENGTH
    long_segment = "a" * 500
    loc = ("body",) + tuple(long_segment for _ in range(10))
    pointer = build_from_pydantic_error(loc)
    # Should be truncated and end with ellipsis
    assert pointer.endswith("..."), "Expected truncated pointer to end with '...'"
    # Truncated output should still be a string and reasonably large
    assert isinstance(pointer, str)
    assert len(pointer) > 2000


def test_return_type_and_stability():
    # Ensure function returns a str for mixed input types and does not mutate input
    loc = ["body", "a/b", 1]
    copy_loc = list(loc)
    res = build_from_pydantic_error(loc)
    assert isinstance(res, str)
    assert loc == copy_loc  # input must not be mutated


@pytest.mark.parametrize(
    "loc, expected",
    [
        (("body", "a/b", "c~d"), "/a~1b/c~0d"),
        (("json",), ""),
        (("value", "x", 2), "/x/2"),
    ],
)
def test_parametrized_cases(loc, expected):
    assert build_from_pydantic_error(loc) == expected
