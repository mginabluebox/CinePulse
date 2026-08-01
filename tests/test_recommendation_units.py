import pytest
from bots.get_recommendation import _parse_movie_reason_map, _cosine_similarity
from errors import ParseError


# --- _parse_movie_reason_map ---

def test_parse_movie_reason_map_valid():
    result = _parse_movie_reason_map('{"1": "good match"}')
    assert result == {1: "good match"}


def test_parse_movie_reason_map_empty_dict_raises():
    with pytest.raises(ParseError):
        _parse_movie_reason_map('{}')


def test_parse_movie_reason_map_non_dict_raises():
    with pytest.raises(ParseError):
        _parse_movie_reason_map('[1, 2, 3]')


def test_parse_movie_reason_map_skips_non_numeric_keys():
    result = _parse_movie_reason_map('{"42": "kept", "abc": "skipped"}')
    assert 42 in result
    assert all(isinstance(k, int) for k in result)


def test_parse_movie_reason_map_null_value_becomes_empty_string():
    result = _parse_movie_reason_map('{"7": null}')
    assert result[7] == ""


# --- _cosine_similarity ---

def test_cosine_similarity_identical_vectors():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
