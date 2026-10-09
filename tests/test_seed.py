"""Seed façon Minecraft Java (``golfgen.seed``).

Valeurs de ``String.hashCode()`` et de ``Long.parseLong`` relevées avec Java
(OpenJDK 27, ``java H.java``) ; ``"golf"`` vérifié aussi à la main :
103·31³ + 111·31² + 108·31 + 102 = 3 178 594.
"""

from __future__ import annotations

import pytest

from golfgen.seed import (DEFAULT_SEED, java_string_hash, parse_java_long, parse_seed,
                          seed_u64)

INT64_MIN, INT64_MAX = -2**63, 2**63 - 1

# texte → String.hashCode() (Java)
JAVA_HASHES = {
    "golf": 3178594,
    "Golf": 2225282,
    "9223372036854775808": -1773151197,
    "-9223372036854775809": 1304595159,
    "é": 233,                               # U+00E9 : une unité UTF-16
    "\U0001F3CC": 1773328,                  # 🏌 : deux unités (paire de substitution)
    "golfé\U0001F3CC": 206210583,
    " 42": 32414,                           # pas de trim (Long.parseLong refuse)
    "-": 45,
    "+": 43,
}


@pytest.mark.parametrize("text", ["42", "-1", "0", "-9223372036854775808",
                                  "9223372036854775807"])
def test_java_long_is_itself(text):
    assert parse_seed(text) == (int(text), None)


def test_extremes():
    assert parse_seed("-9223372036854775808") == (INT64_MIN, None)
    assert parse_seed("9223372036854775807") == (INT64_MAX, None)


@pytest.mark.parametrize("text, value", [("+42", 42), ("007", 7), ("-007", -7),
                                         ("١٢", 12)])
def test_java_long_variants(text, value):
    # mêmes résultats que Long.parseLong (signe +, zéros de tête, chiffres Unicode Nd)
    assert parse_seed(text) == (value, None)


@pytest.mark.parametrize("text", ["9223372036854775808", "-9223372036854775809"])
def test_out_of_range_goes_through_hashcode(text):
    assert parse_java_long(text) is None
    assert parse_seed(text) == (JAVA_HASHES[text], text)


@pytest.mark.parametrize("text", sorted(JAVA_HASHES))
def test_java_string_hash(text):
    assert java_string_hash(text) == JAVA_HASHES[text]


@pytest.mark.parametrize("text", ["golf", "Golf", "é", "\U0001F3CC", "golfé\U0001F3CC",
                                  " 42", "-", "+", "4 2", "1e3", "0x10", "1_000"])
def test_text_goes_through_hashcode(text):
    assert parse_seed(text) == (java_string_hash(text), text)


def test_hash_is_signed_32_bits():
    for text in ["a" * 50, "golf" * 30, "￿" * 7]:
        value = java_string_hash(text)
        assert -2**31 <= value < 2**31


@pytest.mark.parametrize("raw", [None, ""])
def test_empty_falls_back_to_default(raw):
    assert parse_seed(raw) == (DEFAULT_SEED, None) == (42, None)
    assert parse_seed(raw, default=-5) == (-5, None)


def test_json_int_same_as_text():
    assert parse_seed(42) == parse_seed("42") == (42, None)
    assert parse_seed(-1) == (-1, None)
    assert parse_seed(2**63) == (JAVA_HASHES["9223372036854775808"], "9223372036854775808")


@pytest.mark.parametrize("raw", [True, 4.0, [4]])
def test_rejects_other_types(raw):
    with pytest.raises(TypeError):
        parse_seed(raw)


def test_u64():
    assert seed_u64(-1) == 2**64 - 1
    assert seed_u64(INT64_MIN) == 2**63
    for seed in (0, 1, 42, INT64_MAX):
        assert seed_u64(seed) == seed
