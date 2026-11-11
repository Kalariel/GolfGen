"""``tools.dressing.common`` : lecture des seeds en argument (``parse_seeds``)."""

import pytest

from tools.dressing.common import parse_seeds


def test_parse_seeds():
    assert parse_seeds("1-3") == (1, 2, 3)
    assert parse_seeds("3,7") == (3, 7)
    assert parse_seeds(" 3, 7 ") == (3, 7)
    for bad in ("", "  ", ",", "a-b", "1-2-3"):
        with pytest.raises(ValueError):
            parse_seeds(bad)


@pytest.mark.parametrize("bad", ["3,,7", "3,7,", ",3", "3, ,7"])
def test_parse_seeds_rejects_empty_items(bad):
    with pytest.raises(ValueError, match="élément vide"):
        parse_seeds(bad)
