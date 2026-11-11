"""Pipeline (``pipeline.py``) : config, CLI, seed, routage Muirfield, bunkers,
chemins, écriture atomique."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest

import pipeline
from golfgen import exporter as exporter_module
from golfgen import terrain as terrain_module
from golfgen.config import COURSE_PATTERNS, STYLES, CourseConfig
from golfgen.dressing import CourseJsonError, DressingError
from golfgen.dressing.bunkers import BunkerError
from golfgen.dressing.bunkers.selection import EMPTY_RULE
from golfgen.exporter import write_json_atomic
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import load_terrain, water_mask
from golfgen.seed import seed_u64
from golfgen.terrain import TerrainGenerator, terrain_cache_path
from tests.frozen import normalize_frozen

REPO_ROOT = Path(__file__).resolve().parents[1]

# seed 4 en 400×300 : « random » → muirfield_inverse, sans relance (cf. test_exporter_v3)
SEED, WIDTH, HEIGHT = 4, 400, 300


def resolve(argv: list[str]) -> tuple[CourseConfig, str | None]:
    return pipeline.resolve_config(pipeline.build_parser().parse_args(argv))


@pytest.fixture
def no_default_config(tmp_path, monkeypatch):
    """Répertoire courant sans ``default_config.json`` : défauts du dataclass."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def terrain_forbidden(monkeypatch):
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        raise AssertionError("relief calculé avant la validation des paramètres")

    monkeypatch.setattr(pipeline, "load_or_compute", spy)
    return calls


@pytest.fixture(scope="module")
def heightmap4():
    return load_terrain(SEED, WIDTH, HEIGHT)


@pytest.fixture(scope="module")
def result4(heightmap4):
    return mf.build_course(SEED, "random", heightmap4, width=WIDTH, height=HEIGHT)


@pytest.fixture
def cached_relief(monkeypatch, heightmap4):
    """``load_or_compute`` renvoie le relief de la seed 4 (400×300) sans le recalculer."""
    def fake(config, cache_dir=None):
        assert (config.height, config.width) == heightmap4.shape
        return heightmap4, True

    monkeypatch.setattr(pipeline, "load_or_compute", fake)


# ----------------------------------------------------------------------
# Config et CLI
# ----------------------------------------------------------------------

def test_patterns_match_router():
    assert COURSE_PATTERNS == mf.PATTERN_CHOICES


@pytest.mark.parametrize("where", ["dataclass", "default_config.json"])
def test_default_is_landscape_400x300_random(where, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path if where == "dataclass" else REPO_ROOT)
    config, seed_input = resolve([])
    assert (config.width, config.height) == (400, 300)
    assert config.course.orientation == "landscape"
    assert (config.course.short_side, config.course.long_side) == (300, 400)
    assert config.course.pattern == "random"
    assert (config.seed, seed_input) == (42, None)


def test_portrait_mapping(no_default_config):
    config, _ = resolve(["--orientation", "portrait", "--short", "320", "--long", "450"])
    assert (config.width, config.height) == (320, 450)
    config, _ = resolve(["--short", "320", "--long", "450"])
    assert (config.width, config.height) == (450, 320)
    config, _ = resolve(["--orientation", "portrait"])
    assert (config.width, config.height) == (300, 400)


def test_width_height_aliases(no_default_config):
    config, _ = resolve(["--width", "300", "--height", "500", "--pattern", "muirfield"])
    assert (config.width, config.height) == (300, 500)
    assert config.course.pattern == "muirfield"


@pytest.mark.parametrize("argv", [
    ["--short", "299"], ["--short", "351"], ["--long", "399"], ["--long", "501"],
    ["--orientation", "portrait", "--long", "520"],
    ["--width", "350", "--height", "350"],            # alias : mêmes bornes
    ["--width", "600"],
])
def test_out_of_bounds_rejected_before_terrain(argv, no_default_config, terrain_forbidden,
                                               tmp_path, capsys):
    output = tmp_path / "course.json"
    with pytest.raises(SystemExit) as exc:
        pipeline.main([*argv, "--output", str(output)])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER == 2
    assert terrain_forbidden == []
    assert not output.exists()
    assert "hors bornes" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["--width", "400", "--short", "300"],
    ["--height", "300", "--long", "400"],
    ["--width", "400", "--height", "300", "--orientation", "landscape"],
])
def test_aliases_exclusive_with_shape(argv, no_default_config, terrain_forbidden, capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(argv)
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert terrain_forbidden == []
    assert "exclusifs" in capsys.readouterr().err


def test_course_section_read_from_json(tmp_path, no_default_config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"seed": "golf", "course": {
        "pattern": "muirfield", "orientation": "portrait",
        "short_side": 310, "long_side": 420}}), encoding="utf-8")
    config = CourseConfig.from_json(path)
    assert (config.width, config.height) == (310, 420)
    assert config.course.pattern == "muirfield"
    assert (config.seed, config.seed_input) == (3178594, "golf")

    config, seed_input = resolve(["--config", str(path)])
    assert (config.width, config.height) == (310, 420)
    assert (config.seed, seed_input) == (3178594, "golf")
    config, seed_input = resolve(["--config", str(path), "--seed", "-3", "--long", "480"])
    assert (config.width, config.height) == (310, 480)
    assert (config.seed, seed_input) == (-3, None)
    for blank in ("", "   ", "\t"):
        config, seed_input = resolve(["--config", str(path), "--seed", blank])
        assert (config.seed, seed_input) == (3178594, "golf")
    config, seed_input = resolve(["--config", str(path), "--seed", " 42 "])
    assert (config.seed, seed_input) == (42, None)
    config, seed_input = resolve(["--config", str(path), "--seed", " golf "])
    assert (config.seed, seed_input) == (3178594, " golf ")


def test_legacy_routing_section_ignored_with_warning(tmp_path, no_default_config, capsys):
    """Ancienne config avec ``routing`` (routeur retiré) : lisible, section
    ignorée, avertissement sur stderr ; sans la section, aucun avertissement."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"seed": 7, "routing": {"grid_margin": 15}}), encoding="utf-8")
    config = CourseConfig.from_json(path)
    assert config.seed == 7 and not hasattr(config, "routing")
    assert config.to_dict() == CourseConfig(seed=7).to_dict()
    assert "section « routing » ignorée" in capsys.readouterr().err

    CourseConfig.from_json(REPO_ROOT / "default_config.json")
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("raw, seed, seed_input", [
    ("golf", 3178594, "golf"), (" 42 ", 42, None), ("-007", -7, None), (7, 7, None),
    ("", 42, None), ("  ", 42, None), (None, 42, None), (2**63, -1773151197, str(2**63)),
    ("\U0001D7CF", 1773114, "\U0001D7CF"),        # hashCode : 0xD835·31 + 0xDFCF
])
def test_from_json_normalizes_seed(raw, seed, seed_input, tmp_path, no_default_config):
    # toute config chargée a une seed entière normalisée : aucun texte vers le relief
    path = tmp_path / "config.json"
    path.write_text(json.dumps({} if raw is None else {"seed": raw}), encoding="utf-8")
    config = CourseConfig.from_json(path)
    assert type(config.seed) is int
    assert (config.seed, config.seed_input) == (seed, seed_input)
    assert terrain_cache_path(config).name.startswith(f"terrain_s{seed}_")


@pytest.mark.parametrize("raw", [4.5, True, [4], {"a": 1}])
def test_bad_json_seed_rejected_before_terrain(raw, tmp_path, no_default_config,
                                              terrain_forbidden, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"seed": raw}), encoding="utf-8")
    with pytest.raises(ValueError, match="seed"):
        CourseConfig.from_json(path)
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--config", str(path)])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert terrain_forbidden == []
    assert "seed" in capsys.readouterr().err


def test_help_lists_exit_codes(capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--help"])
    assert exc.value.code == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "Codes de sortie : 0 succes, 2 parametre invalide, 3 aucun parcours valide" in out


def test_json_aliases_exclusive_with_course_sides(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"width": 400, "course": {"short_side": 300}}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="exclusifs"):
        CourseConfig.from_json(path)


@pytest.mark.parametrize("course, message", [
    ({"pattern": "links"}, "patron inconnu"),
    ({"orientation": "square"}, "orientation inconnue"),
    ({"style": "desert"}, "style inconnu"),
    ({"style": 3}, "style inconnu"),
    ({"long_side": 380}, "hors bornes"),
])
def test_invalid_json_course_rejected_before_terrain(course, message, tmp_path,
                                                     terrain_forbidden, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"course": course}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--config", str(path)])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert terrain_forbidden == []
    assert message in capsys.readouterr().err


# ----------------------------------------------------------------------
# Étape holes : routeur Muirfield, format 3.1, écriture atomique
# ----------------------------------------------------------------------

def test_happy_path_writes_valid_v3(tmp_path, no_default_config, cached_relief, capsys):
    """Sans bunkers (``--no-bunkers``) : le 3.1 d'avant, sans clé ``bunkers``."""
    output = tmp_path / "out" / "course.json"
    assert pipeline.main(["--seed", str(SEED), "--no-bunkers", "--output", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    meta = data["metadata"]
    assert meta["version"] == "3.1" and "bunkers" not in data
    assert (meta["seed"], meta["seed_input"]) == ("4", None)
    assert meta["pattern"] == {"requested": "random", "resolved": "muirfield_inverse"}
    assert (meta["width"], meta["height"], meta["orientation"]) == (400.0, 300.0, "landscape")
    assert meta["stats"]["par"] == 72
    assert [hole["id"] for hole in data["routing"]["holes"]] == list(range(1, 19))
    assert len(data["routing"]["links"]) == 20
    assert "waypoints" not in output.read_text(encoding="utf-8")
    assert sorted(p.name for p in output.parent.iterdir()) == ["course.json"]
    out = capsys.readouterr().out
    assert "1/3  Terrain (cached)" in out and "Bunkers" not in out and "Chemins" not in out
    assert "paths" not in data
    assert "     Départs : " in out and "trous à 1/2/3 boîtes : " in out
    assert meta["style"] == "links"
    assert all(list(hole["features"]) == ["green", "tees", "fairway"]
               for hole in data["routing"]["holes"])
    # R3f (PAIR_DISTANCE [12, 20]) : plus de green double sur la seed 4
    # (R3d : [[2, 8]]) ; la paire réelle est testée dans test_dressing.py
    assert data["routing"]["green_pairs"] == []


def test_style_default_and_cli(no_default_config):
    assert resolve([])[0].course.style == "links"
    for style in STYLES:
        assert resolve(["--style", style])[0].course.style == style


def test_invalid_style_rejected_before_terrain(no_default_config, terrain_forbidden, capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--style", "desert"])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER == 2
    assert terrain_forbidden == []
    assert "--style" in capsys.readouterr().err


def test_style_never_changes_routing(tmp_path, no_default_config, cached_relief):
    routing = {}
    for style in STYLES:
        output = tmp_path / f"{style}.json"
        assert pipeline.main(["--seed", str(SEED), "--style", style, "--no-bunkers",
                              "--output", str(output)]) == 0
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["metadata"]["style"] == style
        assert isinstance(data["routing"].pop("green_pairs"), list)   # habillage
        for hole in data["routing"]["holes"]:
            hole.pop("features")
        routing[style] = json.dumps(data["routing"])
    assert routing["links"] == routing["parkland"]


def test_output_redressable_from_json_alone(tmp_path, no_default_config, cached_relief):
    """Bouton 2 : le fichier écrit suffit à ré-habiller sans re-router ; même
    habillage au bit près, dans le style d'origine comme dans l'autre."""
    from golfgen.dressing import dress_course_json
    from golfgen.exporter import with_dressing
    files = {}
    for style in STYLES:
        output = tmp_path / f"{style}.json"
        assert pipeline.main(["--seed", str(SEED), "--style", style, "--no-bunkers",
                              "--output", str(output)]) == 0
        files[style] = json.loads(output.read_text(encoding="utf-8"))
    for style, data in files.items():
        assert with_dressing(data, dress_course_json(data, style)) == data
        other = next(s for s in STYLES if s != style)
        redressed = with_dressing(data, dress_course_json(data, other))
        expected = copy.deepcopy(files[other])
        # seule différence admise : la durée de routage des deux exécutions
        redressed["metadata"]["stats"]["elapsed_seconds"] = 0.0
        expected["metadata"]["stats"]["elapsed_seconds"] = 0.0
        assert redressed == expected


# ----------------------------------------------------------------------
# Bunkers (R6), chemins (lot 4 R4) et arbres (lot 5 R4) : actifs par défaut,
# JSON 3.4 ; --no-trees = 3.3 d'avant, --no-paths = 3.2 d'avant, --no-bunkers
# (sans chemins) = 3.1 d'avant
# ----------------------------------------------------------------------

def _run_seed4(directory, heightmap4, extras) -> tuple[list[dict], list[str], list[bytes]]:
    """Exécutions de la seed 4 (relief en mémoire) : JSON, sortie console
    et octets du fichier écrit de chacune."""
    runs, outputs, raw = [], [], []
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(directory)
        patch.setattr(pipeline, "load_or_compute", lambda config, cache_dir=None: (heightmap4, True))
        for i, extra in enumerate(extras):
            output = directory / f"course{i}.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                assert pipeline.main(["--seed", str(SEED), *extra, "--output", str(output)]) == 0
            raw.append(output.read_bytes())
            runs.append(json.loads(raw[-1].decode("utf-8")))
            outputs.append(stdout.getvalue())
    return runs, outputs, raw


@pytest.fixture(scope="module")
def bunkered(tmp_path_factory, heightmap4):
    """Deux exécutions ``--no-trees`` (bunkers et chemins, le 3.3) et une
    ``--no-bunkers`` de la seed 4 : (JSON, JSON, sortie console de la
    première, JSON sans bunkers)."""
    runs, outputs, _ = _run_seed4(tmp_path_factory.mktemp("bunkers"), heightmap4,
                                  (["--no-trees"], ["--no-trees"], ["--no-bunkers"]))
    return runs[0], runs[1], outputs[0], runs[2]


@pytest.fixture(scope="module")
def unpathed(tmp_path_factory, heightmap4):
    """Exécutions ``--no-paths`` et ``--paths-debug`` de la seed 4 : (JSON
    et octets du fichier sans chemins, sortie console ; JSON avec détail)."""
    runs, outputs, raw = _run_seed4(tmp_path_factory.mktemp("paths"), heightmap4,
                                    (["--no-paths"], ["--paths-debug", "--no-trees"]))
    return runs[0], raw[0], outputs[0], runs[1]


def test_bunkers_exported_by_default(bunkered, heightmap4):
    data, _, out, _ = bunkered
    assert data["metadata"]["version"] == "3.3"
    assert list(data) == ["metadata", "terrain", "routing", "bunkers", "paths"]
    section = data["bunkers"]
    assert list(section) == ["empty_rule", "empty_holes", "items"]
    assert section["empty_rule"] == EMPTY_RULE == "per_hole" and isinstance(section["empty_holes"], list)
    items = section["items"]
    assert items and all(list(item) == ["id", "hole", "family", "role", "status", "cells"] for item in items)
    assert [item["hole"] for item in items] == sorted(item["hole"] for item in items)
    assert not {item["hole"] for item in items} & set(section["empty_holes"])
    assert len({(item["hole"], item["id"]) for item in items}) == len(items)
    water = water_mask(heightmap4).water
    height, width = water.shape
    for item in items:
        cells = np.array(item["cells"])
        assert cells.dtype.kind == "i" and cells.ndim == 2 and cells.shape[1] == 2 and len(cells)
        assert (cells >= 0).all() and (cells[:, 0] < width).all() and (cells[:, 1] < height).all()
        assert not water[cells[:, 1], cells[:, 0]].any(), item["id"]      # sable au sec
    assert "4/5  Bunkers (trous vides : per_hole)" in out and "1/5  Terrain (cached)" in out
    assert f"     {len(items)} posé(s) : " in out and " non posé(s)" in out
    assert out.index("4/5  Bunkers") < out.index("5/5  Chemins") < out.index("Export: ")
    assert "format 3.3)" in out


def test_bunkers_deterministic(bunkered):
    first, second, _, _ = bunkered
    assert first["bunkers"] == second["bunkers"]
    first, second = copy.deepcopy(first), copy.deepcopy(second)
    first["metadata"]["stats"]["elapsed_seconds"] = second["metadata"]["stats"]["elapsed_seconds"] = 0.0
    assert first == second


def test_no_bunkers_same_json_but_version_and_key(bunkered):
    """``--no-bunkers`` implique ``--no-paths`` : le 3.1, sans bunkers ni
    chemins."""
    data, _, _, plain = bunkered
    assert "bunkers" not in plain and "paths" not in plain and plain["metadata"]["version"] == "3.1"
    data = copy.deepcopy(data)
    del data["bunkers"], data["paths"]
    data["metadata"]["version"] = "3.1"
    data["metadata"]["stats"]["elapsed_seconds"] = plain["metadata"]["stats"]["elapsed_seconds"]
    assert data == plain


def test_bunkers_recomputed_from_json_alone(bunkered):
    """Étapes rejouées depuis le fichier 3.3 seul : même habillage, mêmes
    bunkers (le 3.2, chemins retirés), mêmes chemins."""
    from golfgen.dressing import dress_course_json
    from golfgen.dressing.bunkers import place_bunkers_json
    from golfgen.dressing.paths import place_paths
    from golfgen.exporter import with_bunkers, with_dressing, with_paths
    data = bunkered[0]
    dressing = dress_course_json(data, data["metadata"]["style"])
    v32 = with_bunkers(with_dressing(data, dressing), place_bunkers_json(data, dressing))
    assert v32 == {**{k: v for k, v in data.items() if k != "paths"},
                   "metadata": {**data["metadata"], "version": "3.2"}}
    assert with_paths(v32, place_paths(v32)) == data


# empreinte de la sortie 3.2 (``--no-paths``) et 3.1 (``--no-bunkers``) de
# la seed 4 relevée AVANT le lot 4 R4 (habillage 0f304e9), JSON écrit par
# ``write_json_atomic`` avec ``metadata.stats.elapsed_seconds`` mis à 0
# (seul champ qui dépend de l'horloge) et ``metadata.generator`` ramené à la
# version du paquet au relevé (seul champ qui dépend de la version)
NO_PATHS_SHA_SEED4 = "3480b568ac4b55f53c29113f81ac8d26d3471e7cd4e3249dce9fe8f37e627308"
NO_BUNKERS_SHA_SEED4 = "a0ace8459b38d77bf612793f2d27c6f17d6835d951d167156ce51334a09b55d6"


def _frozen_sha(data: dict) -> str:
    return _sha(json.dumps(normalize_frozen(data), indent=2, ensure_ascii=False).encode("utf-8"))


# empreinte du 3.3 par défaut de la seed 4, relevée au 2026-11-08 sur f208092
# (avant le retrait de l'étude et des variantes ``legacy``, voir
# ``tests/test_dressing_paths_frozen.py``) ; même calcul que ci-dessus
PATHS_SHA_SEED4 = "7972b670bc250026646e4972e4b9452480d0d82ee18831fd4b453b06c6b1cffa"


def test_default_output_is_frozen(bunkered):
    assert bunkered[0]["metadata"]["version"] == "3.3"
    assert _frozen_sha(bunkered[0]) == PATHS_SHA_SEED4


def test_no_paths_is_the_3_2_of_before_byte_for_byte(unpathed, bunkered):
    """``--no-paths`` : le 3.2 d'avant les chemins, à l'octet près (même
    fichier que ``write_json_atomic``, empreinte figée), sans ligne
    « Chemins » ; le 3.3 (``--no-trees``) n'en diffère que par la clé ``paths``
    et la version ; ``--no-bunkers`` : le 3.1 d'avant, inchangé."""
    plain, raw, out, _ = unpathed
    assert plain["metadata"]["version"] == "3.2" and "paths" not in plain and "trees" not in plain
    assert "trees" not in bunkered[3]
    assert raw == json.dumps(plain, indent=2, ensure_ascii=False).encode("utf-8")
    assert _frozen_sha(plain) == NO_PATHS_SHA_SEED4
    assert _frozen_sha(bunkered[3]) == NO_BUNKERS_SHA_SEED4
    assert "4/4  Bunkers" in out and "Chemins" not in out and "format 3.2)" in out
    data = copy.deepcopy(bunkered[0])
    del data["paths"]
    data["metadata"]["version"] = "3.2"
    data["metadata"]["stats"]["elapsed_seconds"] = plain["metadata"]["stats"]["elapsed_seconds"]
    assert data == plain


def test_paths_exported_by_default(bunkered, heightmap4):
    """Clé ``paths`` (3.3) : couche à plat conforme au schéma (entiers,
    triés, sans doublon, dans la carte), ponts sous-ensemble de ``cells``,
    parvis à part, ancrages hors des chemins ; pas de détail par défaut."""
    data, again, out, _ = bunkered
    section = data["paths"]
    assert list(section) == ["width", "cells", "bridge_cells", "plaza", "anchors"]
    assert section["width"] == 2.0                           # links
    height, width = heightmap4.shape
    layers = {name: section[name] for name in ("cells", "bridge_cells", "anchors")}
    if section["plaza"] is not None:
        assert list(section["plaza"]) == ["cells", "size", "offset"]
        assert len(section["plaza"]["cells"]) == section["plaza"]["size"] ** 2
        offset = section["plaza"]["offset"]
        assert list(offset) == ["along", "inward"] and all(type(v) is int for v in offset.values())
        layers["plaza"] = section["plaza"]["cells"]
    for name, cells in layers.items():
        assert all(len(c) == 2 and all(type(v) is int for v in c) for c in cells), name
        rows = [tuple(c) for c in cells]
        assert rows == sorted(set(rows)), name
        assert all(0 <= x < width and 0 <= z < height for x, z in rows), name
    union = {tuple(c) for c in section["cells"]}
    assert section["cells"] and {tuple(c) for c in section["bridge_cells"]} <= union
    assert not union & {tuple(c) for c in layers.get("plaza", [])}
    assert not union & {tuple(c) for c in section["anchors"]}
    assert again["paths"] == section                         # déterministe
    assert "5/5  Chemins (largeur 2) : 20 liaison(s), " in out


def test_paths_debug_adds_the_link_detail(unpathed, bunkered):
    """``--paths-debug`` : même couche, plus ``paths.debug`` (dernière
    sous-clé) : une entrée par liaison de ``routing.links``."""
    _, _, _, detailed = unpathed
    data = bunkered[0]
    section = detailed["paths"]
    assert list(section) == ["width", "cells", "bridge_cells", "plaza", "anchors", "debug"]
    assert {k: v for k, v in section.items() if k != "debug"} == data["paths"]
    debug = section["debug"]
    assert list(debug) == ["links", "union_added", "union_defects"]
    links = data["routing"]["links"]
    assert len(debug["links"]) == len(links)
    union = {tuple(c) for c in section["cells"]}
    for entry, link in zip(debug["links"], links):
        assert list(entry) == ["from", "to", "status", "bridge", "points", "cells"]
        assert (entry["from"], entry["to"]) == (link["from"], link["to"])
        assert entry["status"] in ("straight", "detour", "bridge", "trivial")
        assert entry["bridge"] == (entry["status"] == "bridge")
        assert all(list(p) == ["x", "y"] for p in entry["points"]) and len(entry["points"]) >= 2
        assert {tuple(c) for c in entry["cells"]} <= union
    assert union == {tuple(c) for e in debug["links"] for c in e["cells"]} | \
        {tuple(c) for c in debug["union_added"]}
    assert debug["union_defects"] == []


@pytest.mark.parametrize("argv", [["--paths-debug", "--no-paths"], ["--paths-debug", "--no-bunkers"]])
def test_paths_debug_needs_paths(argv, no_default_config, terrain_forbidden, capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--seed", str(SEED), *argv])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert "--paths-debug demande les chemins" in capsys.readouterr().err


def test_run_pipeline_refuses_paths_without_bunkers(tmp_path, no_default_config):
    config, _ = resolve(["--seed", str(SEED)])
    with pytest.raises(ValueError, match="chemins sans bunkers"):
        pipeline.run_pipeline(config, tmp_path / "course.json", bunkers=False, paths=True)
    with pytest.raises(ValueError, match="sans chemins"):
        pipeline.run_pipeline(config, tmp_path / "course.json", paths=False, paths_debug=True)
    assert not (tmp_path / "course.json").exists()


def test_paths_failure_exits_cleanly(tmp_path, no_default_config, cached_relief,
                                     monkeypatch, capsys):
    # PathError (liaison sans route : un bogue par construction) : même code
    # que les bunkers, rien n'est écrit, message explicite
    import golfgen.dressing.paths as paths_module
    from golfgen.dressing.paths import PathError

    def failing_paths(data):
        raise PathError("chemins : aucune route pour la liaison 3")

    monkeypatch.setattr(paths_module, "place_paths", failing_paths)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert (f"Tracé des chemins impossible pour la seed {SEED} (style links) : chemins : aucune "
            "route pour la liaison 3. Bogue du tracé, aucun fichier écrit ; --no-paths pour "
            "s'en passer.") in err
    assert "Traceback" not in err


def test_paths_bad_json_exits_cleanly(tmp_path, no_default_config, cached_relief,
                                      monkeypatch, capsys):
    # CourseJsonError à la relecture du 3.2 par le tracé des chemins : code
    # 3, rien n'est écrit, message propre (ni « bogue du tracé » ni trace)
    import golfgen.dressing.paths as paths_module
    error = CourseJsonError("routing.links doit être une liste")

    def failing_paths(data):
        raise error

    monkeypatch.setattr(paths_module, "place_paths", failing_paths)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert (f"JSON non lisible par le tracé des chemins pour la seed {SEED} : {error}. "
            "Aucun fichier écrit.") in err
    assert "Bogue du tracé" not in err and "Traceback" not in err


def test_paths_line_reports_unbridged_corner_contacts():
    # union_defects (aucun attendu) : signalés sur la ligne de l'étape,
    # absents de la ligne quand il n'y en a pas
    from types import SimpleNamespace
    import numpy as np
    debug = SimpleNamespace(links=[SimpleNamespace(status="straight")],
                            union_added=np.zeros((1, 2)), union_defects=())
    paths = SimpleNamespace(width=2.0, cells=np.zeros((5, 2)), bridge_cells=np.zeros((0, 2)),
                            plaza=None, anchors=np.zeros((0, 2)), debug=debug)
    line = pipeline._paths_line(paths, 0.5)
    assert line.endswith("1 raccord(s)  (0.5s)") and "non raccordé" not in line
    debug.union_defects = (((5, 6), (6, 7)), ((1, 1), (2, 2)))
    assert pipeline._paths_line(paths, 0.5).endswith(
        "1 raccord(s), 2 contact(s) non raccordé(s)  (0.5s)")


def test_paths_bug_is_not_swallowed(tmp_path, no_default_config, cached_relief, monkeypatch):
    import golfgen.dressing.paths as paths_module

    def buggy_paths(data):
        raise ValueError("bogue interne")

    monkeypatch.setattr(paths_module, "place_paths", buggy_paths)
    output = tmp_path / "course.json"
    with pytest.raises(ValueError, match="bogue interne"):
        pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert not output.exists()


# ----------------------------------------------------------------------
# Arbres (lot 5 R4) : JSON 3.4 par défaut
# ----------------------------------------------------------------------

TREE_KEYS = ["x", "z", "radius", "layer"]
TREE_LAYERS = ("retombee", "green", "ancrage", "lisiere", "remplissage")


@pytest.fixture(scope="module")
def treed(tmp_path_factory, heightmap4):
    """Seed 4 : (runs, sorties, octets) de ``[]``, ``--no-trees``,
    ``--trees-debug``, ``--tree-margin 0`` et ``--paths-debug``."""
    return _run_seed4(tmp_path_factory.mktemp("trees"), heightmap4,
                      ([], ["--no-trees"], ["--trees-debug"], ["--tree-margin", "0"], ["--paths-debug"]))


def _without(data: dict, *paths: tuple) -> dict:
    data = copy.deepcopy(data)
    data["metadata"]["stats"]["elapsed_seconds"] = 0.0
    for keys in paths:
        target = data
        for key in keys[:-1]:
            target = target[key]
        del target[keys[-1]]
    return data


def test_default_output_is_the_3_4(treed, bunkered, heightmap4):
    runs, outputs, _ = treed
    data = runs[0]
    assert data["metadata"]["version"] == "3.4"
    assert list(data) == ["metadata", "terrain", "routing", "bunkers", "paths", "trees"]
    assert list(data["trees"]) == ["items"]
    height, width = heightmap4.shape
    for item in data["trees"]["items"]:
        assert list(item) == TREE_KEYS + (["grove"] if item["layer"] == "ancrage" else []), item
        assert all(isinstance(item[key], int) and not isinstance(item[key], bool) for key in ("x", "z", "radius"))
        assert item["layer"] in TREE_LAYERS and item["radius"] in (2, 3, 4)
        radius = item["radius"]
        assert radius <= item["x"] < width - radius and radius <= item["z"] < height - radius
    additive = _without(data, ("trees",))
    additive["metadata"]["version"] = "3.3"
    assert additive == _without(bunkered[0])
    assert "5/6  Chemins" in outputs[0] and "6/6  Arbres (marge 5) :" in outputs[0] and "format 3.4)" in outputs[0]


def test_given_scene_matches_a_recomputed_scene(treed):
    """La scène des chemins, passée à ``place_trees``, donne les arbres
    d'une scène recalculée depuis le JSON écrit."""
    from golfgen.dressing.trees import place_trees
    data = treed[0][0]
    recomputed = place_trees(_without(data, ("trees",)))
    assert [exporter_module._tree_item_v34(item) for item in recomputed.items] == data["trees"]["items"]


def test_no_trees_is_the_3_3_of_before_byte_for_byte(treed):
    runs, outputs, raw = treed
    plain = runs[1]
    assert plain["metadata"]["version"] == "3.3" and "trees" not in plain
    assert raw[1] == json.dumps(plain, indent=2, ensure_ascii=False).encode("utf-8")
    assert _frozen_sha(plain) == PATHS_SHA_SEED4
    assert "5/5  Chemins" in outputs[1] and "Arbres" not in outputs[1] and "format 3.3)" in outputs[1]


def test_trees_debug_only_adds_the_debug_key(treed):
    runs, _, _ = treed
    default, detailed = runs[0], runs[2]
    section = detailed["trees"]
    assert list(section) == ["items", "debug"] and section["items"] == default["trees"]["items"]
    assert _without(detailed, ("trees", "debug")) == _without(default)
    debug = section["debug"]
    assert list(debug) == ["counts", "skips", "groves"]
    assert sum(debug["counts"].values()) == len(section["items"])
    assert set(debug["skips"]) == set(debug["counts"]) == set(TREE_LAYERS)
    for grove in debug["groves"]:
        assert list(grove) == ["index", "anchor", "placed", "target", "trees", "motif"]
        assert grove["placed"] == len(grove["trees"]) <= grove["target"]
        assert grove["motif"] in (None, "partiel", "sans_place")
    assert len(debug["groves"]) == len(default["paths"]["anchors"])


def test_paths_debug_has_no_effect_on_the_rest(treed):
    runs, _, _ = treed
    assert _without(runs[4], ("paths", "debug")) == _without(runs[0])


def test_tree_margin_moves_edge_and_fill_only(treed):
    runs, outputs, _ = treed
    default, narrow = runs[0]["trees"]["items"], runs[3]["trees"]["items"]
    fixed = ("retombee", "green", "ancrage")
    assert [i for i in narrow if i["layer"] in fixed] == [i for i in default if i["layer"] in fixed]
    assert [i for i in narrow if i["layer"] not in fixed] != [i for i in default if i["layer"] not in fixed]
    assert "6/6  Arbres (marge 0) :" in outputs[3]


@pytest.mark.parametrize("margin", ["-3", "12.5", "nan", "inf"])
def test_tree_margin_out_of_range_is_refused(margin, no_default_config, terrain_forbidden, capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--seed", str(SEED), f"--tree-margin={margin}"])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert terrain_forbidden == []
    assert "marge des arbres invalide" in capsys.readouterr().err


@pytest.mark.parametrize("option", [["--trees-debug"], ["--tree-margin", "3"]], ids=lambda o: o[0])
@pytest.mark.parametrize("without", ["--no-trees", "--no-paths", "--no-bunkers"])
def test_tree_options_need_the_trees(option, without, no_default_config, terrain_forbidden, capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--seed", str(SEED), *option, without])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert terrain_forbidden == []
    assert f"{option[0]} demande les arbres" in capsys.readouterr().err


def test_run_pipeline_refuses_trees_without_paths(tmp_path, no_default_config):
    config, _ = resolve(["--seed", str(SEED)])
    with pytest.raises(ValueError, match="arbres sans chemins"):
        pipeline.run_pipeline(config, tmp_path / "course.json", paths=False, trees=True)
    with pytest.raises(ValueError, match="détail des arbres demandé sans arbres"):
        pipeline.run_pipeline(config, tmp_path / "course.json", trees=False, trees_debug=True)
    with pytest.raises(ValueError, match="marge des arbres demandée sans arbres"):
        pipeline.run_pipeline(config, tmp_path / "course.json", trees=False, tree_margin=3.0)
    assert not (tmp_path / "course.json").exists()


@pytest.mark.parametrize("margin", [-3.0, 12.5, float("nan"), float("inf"), True])
def test_run_pipeline_refuses_a_bad_margin_before_routing(margin, tmp_path, no_default_config, terrain_forbidden):
    config, _ = resolve(["--seed", str(SEED)])
    with pytest.raises(ValueError, match="marge des arbres invalide"):
        pipeline.run_pipeline(config, tmp_path / "course.json", tree_margin=margin)
    assert terrain_forbidden == [] and not (tmp_path / "course.json").exists()


def test_tree_failure_exits_cleanly(tmp_path, no_default_config, cached_relief, monkeypatch, capsys):
    # TreeError : un bogue, rien n'est écrit, sans invitation à changer de seed
    import golfgen.dressing.trees as trees_module
    from golfgen.dressing.trees import TreeError

    def failing(data, margin, scene):
        raise TreeError("zone divergente")

    monkeypatch.setattr(trees_module, "place_trees", failing)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    assert pipeline.main(["--seed", str(SEED), "--output", str(output)]) == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert (f"Pose des arbres interrompue pour la seed {SEED} (style links) : zone divergente. "
            "Bogue de la pose, aucun fichier écrit ; --no-trees pour s'en passer.") in err
    assert "autre seed" not in err and "Traceback" not in err


def test_tree_bug_is_not_swallowed(tmp_path, no_default_config, cached_relief, monkeypatch):
    import golfgen.dressing.trees as trees_module

    def buggy(data, margin, scene):
        raise ValueError("bogue interne")

    monkeypatch.setattr(trees_module, "place_trees", buggy)
    output = tmp_path / "course.json"
    with pytest.raises(ValueError, match="bogue interne"):
        pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert not output.exists()


def test_with_trees_needs_paths(treed):
    from golfgen.dressing.trees import CourseTrees
    trees = CourseTrees((), {}, {}, ())
    with pytest.raises(ValueError, match="arbres sans chemins"):
        exporter_module.with_trees({"terrain": {"width": 9, "height": 9}}, trees)
    with pytest.raises(TypeError, match="CourseTrees"):
        exporter_module.with_trees(treed[0][1], "pas des arbres")


def test_with_trees_refuses_a_crown_off_the_map(treed):
    from golfgen.dressing.trees import CourseTrees, TreeItem
    trees = CourseTrees((TreeItem(1, 50, 3, "lisiere"),), {}, {}, ())
    with pytest.raises(ValueError, match="hors de la carte"):
        exporter_module.with_trees(treed[0][1], trees)


def test_earlier_steps_drop_the_trees_key(treed):
    from golfgen.dressing import dress_course_json
    from golfgen.dressing.bunkers import CourseBunkers
    from golfgen.dressing.paths import place_paths
    data = treed[0][0]
    style = data["metadata"]["style"]
    dressed = exporter_module.with_dressing(data, dress_course_json(data, style))
    assert list(dressed) == ["metadata", "terrain", "routing"] and dressed["metadata"]["version"] == "3.1"
    bunkered = exporter_module.with_bunkers(data, CourseBunkers(0, (), (), ()))
    assert list(bunkered) == ["metadata", "terrain", "routing", "bunkers"]
    assert bunkered["metadata"]["version"] == "3.2"
    pathed = exporter_module.with_paths(data, place_paths(_without(data, ("trees",))))
    assert list(pathed) == ["metadata", "terrain", "routing", "bunkers", "paths"]
    assert pathed["metadata"]["version"] == "3.3"


def test_trees_line_reports_layers_and_skips():
    from golfgen.dressing.trees import CourseTrees
    trees = CourseTrees((), {"retombee": 2, "green": 1}, {"retombee": {}, "green": {"deux_flancs": 3}}, ())
    assert pipeline._trees_line(trees, 5.0, 1.25, 6) == ("6/6  Arbres (marge 5) : 0 posé(s) (retombee 2, green 1) ; "
                                                         "sauts : green deux_flancs 3  (1.2s)")


def test_bunker_families_are_haricot_and_pot(bunkered):
    """Familles posées : haricots et pots seulement (organiques retirés) ;
    aucune mention des organiques dans la console."""
    data, _, out, _ = bunkered
    families = {item["family"] for item in data["bunkers"]["items"]}
    assert families <= {"haricot", "pot"} and "haricot" in families
    assert "organique" not in out


@pytest.mark.parametrize("flag", ["--no-organics", "--organics-as-haricots"])
def test_removed_organics_options_are_refused(flag, no_default_config, terrain_forbidden, capsys):
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--seed", str(SEED), flag])
    assert exc.value.code == pipeline.EXIT_BAD_PARAMETER
    assert terrain_forbidden == []
    assert flag in capsys.readouterr().err


@pytest.mark.parametrize("text, signed, seed_input", [
    ("-1", -1, None), ("golf", 3178594, "golf"),
    ("-9223372036854775808", -2**63, None),
])
def test_seed_signed_in_json_u64_to_router(text, signed, seed_input, tmp_path,
                                           no_default_config, cached_relief, result4,
                                           monkeypatch):
    calls = []

    def fake_build(seed, pattern, heightmap, **kwargs):
        calls.append((seed, pattern, kwargs))
        return result4

    monkeypatch.setattr(mf, "build_course", fake_build)
    output = tmp_path / "course.json"
    assert pipeline.main(["--seed", text, "--no-bunkers", "--output", str(output)]) == 0
    assert calls == [(seed_u64(signed), "random", {"width": 400, "height": 300})]
    assert type(calls[0][0]) is int and calls[0][0] >= 0
    meta = json.loads(output.read_text(encoding="utf-8"))["metadata"]
    assert (meta["seed"], meta["seed_input"]) == (str(signed), seed_input)


def test_routing_failure_keeps_existing_output(tmp_path, no_default_config, cached_relief,
                                               monkeypatch, capsys):
    def failing_build(seed, pattern, heightmap, **kwargs):
        raise mf.MuirfieldRoutingError(seed, [{"status": "echec"}])

    monkeypatch.setattr(mf, "build_course", failing_build)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", "-42", "--pattern", "muirfield_inverse",
                          "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert ("Aucun parcours valide pour la seed -42 (patron muirfield_inverse, 400x300) : "
            "essayez une autre seed.") in err


@pytest.mark.parametrize("error", [DressingError("trou 7 : green impossible à inclure dans le cœur"),
                                   DressingError("trou 7 : segment final nul")])
def test_dressing_failure_exits_cleanly(error, tmp_path, no_default_config, cached_relief,
                                        monkeypatch, capsys):
    import golfgen.dressing as dressing_module

    def failing_dress(*args, **kwargs):
        raise error

    monkeypatch.setattr(dressing_module, "dress_course_json", failing_dress)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert f"Habillage impossible pour la seed {SEED} (style links) : {error}." in err
    assert "Traceback" not in err


@pytest.mark.parametrize("error", [ValueError("bogue interne"), RuntimeError("bogue interne")])
def test_dressing_bug_is_not_swallowed(error, tmp_path, no_default_config, cached_relief,
                                       monkeypatch):
    # Seule DressingError est un échec attendu : un autre type (bogue numpy,
    # shapely…) remonte au lieu d'être déguisé en « essayez une autre seed »
    import golfgen.dressing as dressing_module

    def buggy_dress(*args, **kwargs):
        raise error

    monkeypatch.setattr(dressing_module, "dress_course_json", buggy_dress)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    with pytest.raises(type(error), match="bogue interne"):
        pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert output.read_bytes() == previous


def test_bunkers_failure_exits_cleanly(tmp_path, no_default_config, cached_relief,
                                       monkeypatch, capsys):
    # BunkerError (géométrie des bunkers dépendante de la seed) : même
    # consigne que l'habillage, rien n'est écrit
    import golfgen.dressing.bunkers as bunkers_module
    error = BunkerError("enveloppe convexe dégénérée (2 sommet(s)) : points confondus ou alignés")

    def failing_place(*args, **kwargs):
        raise error

    monkeypatch.setattr(bunkers_module, "place_bunkers_json", failing_place)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert (f"Pose des bunkers impossible pour la seed {SEED} (style links) : {error}. "
            "Aucun fichier écrit ; essayez une autre seed ou --no-bunkers.") in err
    assert "Traceback" not in err


def test_bunkers_bad_json_exits_cleanly(tmp_path, no_default_config, cached_relief,
                                        monkeypatch, capsys):
    # CourseJsonError (une ValueError) à la relecture : message propre, pas
    # « essayez une autre seed »
    import golfgen.dressing.bunkers as bunkers_module
    error = CourseJsonError("routing.holes doit être une liste")

    def failing_place(*args, **kwargs):
        raise error

    monkeypatch.setattr(bunkers_module, "place_bunkers_json", failing_place)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    err = capsys.readouterr().err
    assert (f"JSON du routage non lisible par la pose des bunkers pour la seed {SEED} : "
            f"{error}. Aucun fichier écrit.") in err
    assert "autre seed" not in err and "Traceback" not in err


@pytest.mark.parametrize("error", [ValueError("bogue interne"), RuntimeError("bogue interne")])
def test_bunkers_bug_is_not_swallowed(error, tmp_path, no_default_config, cached_relief,
                                      monkeypatch):
    # Seule BunkerError est un échec attendu de la pose : une ValueError
    # d'invariant (statut inconnu, poids de mélange…) remonte au lieu d'être
    # déguisée en « essayez une autre seed »
    import golfgen.dressing.bunkers as bunkers_module

    def buggy_place(*args, **kwargs):
        raise error

    monkeypatch.setattr(bunkers_module, "place_bunkers_json", buggy_place)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    with pytest.raises(type(error), match="bogue interne"):
        pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert output.read_bytes() == previous


def test_failed_write_keeps_existing_output(tmp_path, no_default_config, cached_relief,
                                            monkeypatch):
    output = tmp_path / "course.json"
    output.write_bytes(b"ancien")

    def broken_dump(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr(json, "dump", broken_dump)
    with pytest.raises(OSError):
        pipeline.main(["--seed", str(SEED), "--no-bunkers", "--output", str(output)])
    assert output.read_bytes() == b"ancien"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]


def test_write_json_atomic_fsyncs_before_replace(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(exporter_module.os, "fsync",
                        lambda fd: (events.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(exporter_module.os, "replace",
                        lambda a, b: (events.append("replace"), real_replace(a, b))[1])
    path = tmp_path / "course.json"
    write_json_atomic(path, {"a": 1})
    assert events == ["fsync", "replace"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_write_json_atomic_replaces_symlink(tmp_path):
    target = tmp_path / "target.json"
    target.write_bytes(b"cible")
    link = tmp_path / "course.json"
    link.symlink_to(target)
    write_json_atomic(link, {"a": 1})
    assert not link.is_symlink()
    assert json.loads(link.read_text(encoding="utf-8")) == {"a": 1}
    assert target.read_bytes() == b"cible"


# ----------------------------------------------------------------------
# Cache de relief : message « cached » fidèle, shape vérifiée
# ----------------------------------------------------------------------

SMALL = CourseConfig(seed=-42, width=40, height=30)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    monkeypatch.setattr(terrain_module, "TERRAIN_CACHE_DIR", directory)
    return directory


@pytest.fixture
def router_reliefs(monkeypatch):
    """Routeur remplacé par un échec immédiat : la carte 40×30 garde le test
    rapide ; renvoie les reliefs reçus par le routeur."""
    reliefs = []

    def failing_build(seed, pattern, heightmap, **kwargs):
        reliefs.append(heightmap)
        raise mf.MuirfieldRoutingError(seed, [{"status": "echec"}])

    monkeypatch.setattr(mf, "build_course", failing_build)
    return reliefs


def test_cached_message_miss_then_hit(cache_dir, router_reliefs, tmp_path, capsys):
    output = tmp_path / "course.json"
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 output) == pipeline.EXIT_ROUTING_FAILED
    assert "1/6  Terrain (Perlin noise)" in capsys.readouterr().out
    assert [p.name for p in cache_dir.iterdir()] == [terrain_cache_path(SMALL).name]
    assert terrain_cache_path(SMALL).name.startswith("terrain_s-42_40x30_")
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 output) == pipeline.EXIT_ROUTING_FAILED
    assert "1/6  Terrain (cached)" in capsys.readouterr().out
    reference = TerrainGenerator(SMALL).generate()
    assert len(router_reliefs) == 2
    assert all(np.array_equal(relief, reference) for relief in router_reliefs)
    assert not output.exists()


def test_wrong_shape_cache_is_recomputed(cache_dir, router_reliefs, tmp_path, capsys):
    path = terrain_cache_path(SMALL)
    cache_dir.mkdir()
    np.save(path, np.zeros((5, 5), dtype=np.float32))
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 tmp_path / "course.json") == pipeline.EXIT_ROUTING_FAILED
    captured = capsys.readouterr()
    assert "1/6  Terrain (Perlin noise)" in captured.out
    assert "relief recalculé" in captured.err
    reference = TerrainGenerator(SMALL).generate()
    assert np.array_equal(router_reliefs[0], reference)
    assert np.array_equal(np.load(path), reference)
    heightmap, from_cache = terrain_module.load_or_compute(SMALL)
    assert from_cache and np.array_equal(heightmap, reference)


def test_negative_seed_relief_equals_u64():
    # opensimplex ramène la seed sur int64 : signée et u64 donnent le même bruit
    a = TerrainGenerator(CourseConfig(seed=-42, width=40, height=30)).generate()
    b = TerrainGenerator(CourseConfig(seed=seed_u64(-42), width=40, height=30)).generate()
    c = TerrainGenerator(CourseConfig(seed=42, width=40, height=30)).generate()
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


# ----------------------------------------------------------------------
# Non-régression seeds positives (empreintes relevées sur master 52d352c)
# ----------------------------------------------------------------------

RELIEF_42 = "b77bd2667684e8735cf3c05de2d169bc6c6d108291d9a1b051f3ea1073916190"
# « random » (résolu en muirfield_inverse, ~20 s) a la même empreinte avant/après
# (vérifié une fois, a084ca56…) ; laissé hors de la suite pour la garder rapide.
ROUTING_42 = {"muirfield": "9239dace2d3977f3544c4dbd770cd41a03bcc230a4110fe2198d2ce3662a292b"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def relief42():
    return TerrainGenerator(CourseConfig(seed=42, width=WIDTH, height=HEIGHT)).generate()


def test_positive_seed_relief_unchanged(relief42):
    assert _sha(relief42.tobytes()) == RELIEF_42


def _rounded_routing(routing: dict) -> dict:
    """``routing`` tel qu'exporté avant le lot 2 R0 : entrées de l'habillage
    arrondies à 2 décimales, ``rough_margin`` absent."""
    routing = json.loads(json.dumps(routing))

    def r2(point):
        point.update(x=round(point["x"], 2), y=round(point["y"], 2))
    r2(routing["clubhouse"])
    for hole in routing["holes"]:
        hole["width"] = round(hole["width"], 2)
        del hole["rough_margin"]
        for point in (hole["tee"], hole["green"], *hole["doglegs"]):
            r2(point)
    return routing


@pytest.mark.parametrize("pattern", sorted(ROUTING_42))
def test_positive_seed_layout_unchanged(relief42, pattern):
    # empreinte d'avant le lot 2 R0 sur la projection arrondie : le tracé
    # n'a pas changé, seul l'export de ses entrées d'habillage s'est précisé
    from golfgen.exporter import muirfield_to_dict
    result = mf.build_course(seed_u64(42), pattern, relief42, width=WIDTH, height=HEIGHT)
    data = muirfield_to_dict(result, relief42, seed=42)
    assert _sha(json.dumps(_rounded_routing(data["routing"]), sort_keys=True).encode()) \
        == ROUTING_42[pattern]


def test_unreadable_json_exits_cleanly(tmp_path, no_default_config, cached_relief,
                                       monkeypatch, capsys):
    # JSON du routage refusé à la relecture (``CourseJsonError``) : même sortie
    # propre qu'un échec d'habillage, sans écrire
    import golfgen.dressing as dressing_module
    from golfgen.dressing import CourseJsonError

    def refusing_dress(*args, **kwargs):
        raise CourseJsonError("tracé du JSON 3.0 incohérent : liaison 3")

    monkeypatch.setattr(dressing_module, "dress_course_json", refusing_dress)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert (f"JSON du routage non habillable pour la seed {SEED} : tracé du JSON 3.0 "
            "incohérent : liaison 3. Aucun fichier écrit.") in err
    assert "Traceback" not in err


def test_lossy_relief_export_exits_cleanly(tmp_path, no_default_config, cached_relief,
                                           monkeypatch, capsys):
    # relief non exportable sans perte (``relief_f32_block``) : code 3, rien écrit
    def lossy(heightmap):
        raise terrain_module.ReliefExportError("relief non représentable exactement en float32")

    monkeypatch.setattr(exporter_module, "relief_f32_block", lossy)
    output = tmp_path / "course.json"
    previous = b'{"ancien": "parcours"}\n'
    output.write_bytes(previous)
    code = pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
    assert output.read_bytes() == previous
    err = capsys.readouterr().err
    assert (f"Export du routage impossible pour la seed {SEED} : relief non représentable "
            "exactement en float32. Aucun fichier écrit.") in err
    assert "Traceback" not in err


def test_internal_export_error_propagates(tmp_path, no_default_config, cached_relief,
                                          monkeypatch):
    # autre ``ValueError`` de l'export (incohérence interne, ex. contrôle de
    # forme du relief) : pas interceptée comme un relief non exportable
    def broken(heightmap):
        raise ValueError("relief (3, 4), carte attendue 300×400")

    monkeypatch.setattr(exporter_module, "relief_f32_block", broken)
    output = tmp_path / "course.json"
    with pytest.raises(ValueError, match="carte attendue") as info:
        pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert not isinstance(info.value, terrain_module.ReliefExportError)
    assert not output.exists()
