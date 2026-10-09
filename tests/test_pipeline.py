"""Pipeline (``pipeline.py``) : config, CLI, seed, routage Muirfield, écriture atomique."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import pipeline
from golfgen import terrain as terrain_module
from golfgen.config import COURSE_PATTERNS, CourseConfig
from golfgen.routing import muirfield as mf
from golfgen.routing.sites import load_terrain
from golfgen.seed import seed_u64
from golfgen.terrain import TerrainGenerator, terrain_cache_path

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
    assert exc.value.code == 2
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
    assert exc.value.code == 2
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

    config, seed_input = resolve(["--config", str(path)])
    assert (config.width, config.height) == (310, 420)
    assert (config.seed, seed_input) == (3178594, "golf")
    config, seed_input = resolve(["--config", str(path), "--seed", "-3", "--long", "480"])
    assert (config.width, config.height) == (310, 480)
    assert (config.seed, seed_input) == (-3, None)
    config, seed_input = resolve(["--config", str(path), "--seed", ""])
    assert (config.seed, seed_input) == (3178594, "golf")


def test_json_aliases_exclusive_with_course_sides(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"width": 400, "course": {"short_side": 300}}),
                    encoding="utf-8")
    with pytest.raises(ValueError, match="exclusifs"):
        CourseConfig.from_json(path)


@pytest.mark.parametrize("course, message", [
    ({"pattern": "links"}, "patron inconnu"),
    ({"orientation": "square"}, "orientation inconnue"),
    ({"long_side": 380}, "hors bornes"),
])
def test_invalid_json_course_rejected_before_terrain(course, message, tmp_path,
                                                     terrain_forbidden, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"course": course}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--config", str(path)])
    assert exc.value.code == 2
    assert terrain_forbidden == []
    assert message in capsys.readouterr().err


# ----------------------------------------------------------------------
# Étape holes : routeur Muirfield, format 3.0, écriture atomique
# ----------------------------------------------------------------------

def test_happy_path_writes_valid_v3(tmp_path, no_default_config, cached_relief, capsys):
    output = tmp_path / "out" / "course.json"
    assert pipeline.main(["--seed", str(SEED), "--output", str(output)]) == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    meta = data["metadata"]
    assert meta["version"] == "3.0"
    assert (meta["seed"], meta["seed_input"]) == ("4", None)
    assert meta["pattern"] == {"requested": "random", "resolved": "muirfield_inverse"}
    assert (meta["width"], meta["height"], meta["orientation"]) == (400.0, 300.0, "landscape")
    assert meta["stats"]["par"] == 72
    assert [hole["id"] for hole in data["routing"]["holes"]] == list(range(1, 19))
    assert len(data["routing"]["links"]) == 20
    assert "waypoints" not in output.read_text(encoding="utf-8")
    assert sorted(p.name for p in output.parent.iterdir()) == ["course.json"]
    assert "1/2  Terrain (cached)" in capsys.readouterr().out


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
    assert pipeline.main(["--seed", text, "--output", str(output)]) == 0
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
    assert code == 2
    assert output.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]
    err = capsys.readouterr().err
    assert ("Aucun parcours valide pour la seed -42 (patron muirfield_inverse, 400x300) : "
            "essayez une autre seed.") in err


def test_failed_write_keeps_existing_output(tmp_path, no_default_config, cached_relief,
                                            monkeypatch):
    output = tmp_path / "course.json"
    output.write_bytes(b"ancien")

    def broken_dump(*args, **kwargs):
        raise OSError("disque plein")

    monkeypatch.setattr(json, "dump", broken_dump)
    with pytest.raises(OSError):
        pipeline.main(["--seed", str(SEED), "--output", str(output)])
    assert output.read_bytes() == b"ancien"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["course.json"]


# ----------------------------------------------------------------------
# Cache de relief : message « cached » fidèle, shape vérifiée
# ----------------------------------------------------------------------

SMALL = CourseConfig(seed=-42, width=40, height=30)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    monkeypatch.setattr(terrain_module, "TERRAIN_CACHE_DIR", directory)
    return directory


def test_cached_message_miss_then_hit(cache_dir, tmp_path, capsys):
    output = tmp_path / "terrain.json"
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 "terrain", output) == 0
    assert "1/2  Terrain (Perlin noise)" in capsys.readouterr().out
    assert [p.name for p in cache_dir.iterdir()] == [terrain_cache_path(SMALL).name]
    assert terrain_cache_path(SMALL).name.startswith("terrain_s-42_40x30_")
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 "terrain", output) == 0
    assert "1/2  Terrain (cached)" in capsys.readouterr().out


def test_wrong_shape_cache_is_recomputed(cache_dir, tmp_path, capsys):
    path = terrain_cache_path(SMALL)
    cache_dir.mkdir()
    np.save(path, np.zeros((5, 5), dtype=np.float32))
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 "terrain", tmp_path / "terrain.json") == 0
    captured = capsys.readouterr()
    assert "1/2  Terrain (Perlin noise)" in captured.out
    assert "relief recalculé" in captured.err
    reference = TerrainGenerator(SMALL).generate()
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


@pytest.mark.parametrize("pattern", sorted(ROUTING_42))
def test_positive_seed_layout_unchanged(relief42, pattern):
    from golfgen.exporter import muirfield_to_dict
    result = mf.build_course(seed_u64(42), pattern, relief42, width=WIDTH, height=HEIGHT)
    data = muirfield_to_dict(result, relief42, seed=42)
    assert _sha(json.dumps(data["routing"], sort_keys=True).encode()) == ROUTING_42[pattern]
