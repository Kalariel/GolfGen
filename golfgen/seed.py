"""Seed à la Minecraft Java : texte saisi → entier signé 64 bits.

Règle de Minecraft Java (création de monde) : si ``Long.parseLong(texte)``
réussit, la seed est cet entier signé ; sinon (texte quelconque, ou nombre
hors de [−2^63, 2^63 − 1]) c'est ``texte.hashCode()``, entier signé 32 bits
calculé sur les unités de code UTF-16. Comme Minecraft, le texte est d'abord
débarrassé de ses blancs de tête et de queue (``String.trim()`` : caractères
≤ U+0020) : ``" 42 "`` vaut 42, et un texte vide après trim donne la seed par
défaut. ``seed_input`` garde le texte tel que saisi, sans trim.

La seed signée est celle exportée (``metadata.seed``) et celle qui nomme le
cache de relief ; numpy n'acceptant que des entiers positifs, le routage
reçoit ``seed_u64(signed)``, égal à ``signed`` pour toute seed ≥ 0.
"""

from __future__ import annotations

import re

DEFAULT_SEED = 42
INT64_MIN = -(1 << 63)
INT64_MAX = (1 << 63) - 1
U64_MASK = 0xFFFF_FFFF_FFFF_FFFF

# ``Long.parseLong`` : signe optionnel puis au moins un chiffre décimal.
# ``\d`` (catégorie Unicode Nd) comme ``Character.digit(c, 10)`` en Java :
# ``Long.parseLong("١٢")`` vaut 12, ``int("١٢")`` aussi. Java lit des unités
# UTF-16 : un chiffre hors du plan de base (``"𝟏"``, U+1D7CF, paire de
# substitution) n'en est pas un pour lui, d'où ``parse_java_long`` qui exige
# aussi que tout caractère soit ≤ U+FFFF.
_JAVA_LONG = re.compile(r"[+-]?\d+")
_BMP_MAX = 0xFFFF


def java_string_hash(text: str) -> int:
    """``String.hashCode()`` de Java : h = 31·h + c sur les unités UTF-16,
    modulo 2^32, interprété en entier signé 32 bits."""
    data = text.encode("utf-16-be", "surrogatepass")
    h = 0
    for i in range(0, len(data), 2):
        h = (31 * h + ((data[i] << 8) | data[i + 1])) & 0xFFFF_FFFF
    return h - (1 << 32) if h & 0x8000_0000 else h


def java_trim(text: str) -> str:
    """``String.trim()`` de Java : retire en tête et en queue les caractères
    ≤ U+0020 (espace et contrôles ASCII), pas les autres blancs Unicode."""
    start, end = 0, len(text)
    while start < end and text[start] <= " ":
        start += 1
    while end > start and text[end - 1] <= " ":
        end -= 1
    return text[start:end]


def parse_java_long(text: str) -> int | None:
    """``Long.parseLong(text)``, ou None là où Java lève ``NumberFormatException``."""
    if not _JAVA_LONG.fullmatch(text) or any(ord(c) > _BMP_MAX for c in text):
        return None
    value = int(text)
    return value if INT64_MIN <= value <= INT64_MAX else None


def parse_seed(raw: int | str | None, default: int = DEFAULT_SEED) -> tuple[int, str | None]:
    """Seed signée 64 bits et texte d'origine, à partir d'une saisie CLI ou JSON.

    Le texte est d'abord passé par ``java_trim`` (comme Minecraft) ; ensuite :

    - ``None``, ou texte vide après trim → ``(default, None)`` ;
    - entier (JSON) → traité comme son écriture décimale ;
    - texte que ``Long.parseLong`` accepte → ``(entier, None)`` ;
    - sinon → ``(java_string_hash(texte_trimé), texte)``.

    Returns:
        ``(signed, seed_input)`` : ``signed`` est un ``int`` Python dans
        [−2^63, 2^63 − 1] ; ``seed_input`` est le texte d'origine, tel que
        saisi (non trimé), quand il est passé par ``hashCode``, sinon None.
    """
    if raw is None:
        return default, None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise TypeError(f"seed : entier ou chaîne attendu, pas {type(raw).__name__}")
    text = str(raw)
    trimmed = java_trim(text)
    if trimmed == "":
        return default, None
    value = parse_java_long(trimmed)
    if value is not None:
        return value, None
    return java_string_hash(trimmed), text


def seed_u64(signed: int) -> int:
    """Seed non signée pour numpy (``SeedSequence`` refuse les négatifs) :
    complément à deux sur 64 bits, identité pour toute seed ≥ 0."""
    return signed & U64_MASK
