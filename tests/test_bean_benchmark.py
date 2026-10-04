from experiments.bean_paving.benchmark import _similarity


def test_similarity_is_rotation_invariant_fingerprint_comparison():
    fingerprint = ((3, 4), (0, 3), (9, 14), (4,))
    assert _similarity(fingerprint, fingerprint) == 1.0


def test_similarity_detects_different_layouts():
    first = ((3, 4), (0, 3), (9, 14), (4,))
    second = ((5, 5), (6, 9), (20, 22), (1,))
    assert _similarity(first, second) < 0.5
