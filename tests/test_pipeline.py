"""Pipeline (``pipeline.py``) : config, CLI, seed, routage Muirfield, écriture atomique."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

import pipeline
from golfgen import exporter as exporter_module
from golfgen import terrain as terrain_module
from golfgen.config import COURSE_PATTERNS, CourseConfig
from golfgen.exporter import write_json_atomic
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
    assert code == pipeline.EXIT_ROUTING_FAILED == 3
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
    assert "1/2  Terrain (Perlin noise)" in capsys.readouterr().out
    assert [p.name for p in cache_dir.iterdir()] == [terrain_cache_path(SMALL).name]
    assert terrain_cache_path(SMALL).name.startswith("terrain_s-42_40x30_")
    assert pipeline.run_pipeline(CourseConfig(seed=-42, width=40, height=30),
                                 output) == pipeline.EXIT_ROUTING_FAILED
    assert "1/2  Terrain (cached)" in capsys.readouterr().out
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
    assert "1/2  Terrain (Perlin noise)" in captured.out
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


@pytest.mark.parametrize("pattern", sorted(ROUTING_42))
def test_positive_seed_layout_unchanged(relief42, pattern):
    from golfgen.exporter import muirfield_to_dict
    result = mf.build_course(seed_u64(42), pattern, relief42, width=WIDTH, height=HEIGHT)
    data = muirfield_to_dict(result, relief42, seed=42)
    assert _sha(json.dumps(data["routing"], sort_keys=True).encode()) == ROUTING_42[pattern]
