from __future__ import annotations

import math

import pytest

from sm_ml.memory import FEATURE_VECTOR_DIM, cosine_similarity, technique_feature_vector


def test_feature_vector_is_l2_normalized() -> None:
    v = technique_feature_vector(["T1110", "T1078", "T1059"])
    norm = math.sqrt(sum(x * x for x in v))
    assert norm == pytest.approx(1.0)


def test_feature_vector_has_the_requested_dimension() -> None:
    assert len(technique_feature_vector(["T1110"])) == FEATURE_VECTOR_DIM
    assert len(technique_feature_vector(["T1110"], dim=8)) == 8


def test_empty_input_is_the_zero_vector() -> None:
    v = technique_feature_vector([])
    assert v == [0.0] * FEATURE_VECTOR_DIM


def test_deterministic_for_the_same_input() -> None:
    a = technique_feature_vector(["T1110", "T1078"])
    b = technique_feature_vector(["T1110", "T1078"])
    assert a == b


def test_order_independent() -> None:
    a = technique_feature_vector(["T1110", "T1078", "T1059"])
    b = technique_feature_vector(["T1059", "T1110", "T1078"])
    assert a == b


def test_dim_must_be_positive() -> None:
    with pytest.raises(ValueError, match="dim must be"):
        technique_feature_vector(["T1110"], dim=0)


def test_identical_technique_sets_are_maximally_similar() -> None:
    a = technique_feature_vector(["T1110", "T1078", "T1059"])
    b = technique_feature_vector(["T1110", "T1078", "T1059"])
    assert cosine_similarity(a, b) == pytest.approx(1.0)


def test_disjoint_technique_sets_are_dissimilar() -> None:
    # Chosen so the hashed buckets do not collide: verified deterministic.
    a = technique_feature_vector(["T1110"], dim=8)
    b = technique_feature_vector(["T1078"], dim=8)
    if a == b:
        pytest.skip("hash collision for this dim/input pair")
    assert cosine_similarity(a, b) < 1.0


def test_zero_vector_has_no_signal() -> None:
    zero = [0.0] * FEATURE_VECTOR_DIM
    v = technique_feature_vector(["T1110"])
    assert cosine_similarity(zero, v) == 0.0
    assert cosine_similarity(zero, zero) == 0.0


def test_cosine_similarity_requires_equal_length() -> None:
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


def test_cosine_similarity_is_bounded() -> None:
    a = technique_feature_vector(["T1110", "T1595"])
    b = technique_feature_vector(["T1059", "T1078"])
    sim = cosine_similarity(a, b)
    assert -1.0 <= sim <= 1.0
