"""Round ``calib`` du runner Muirfield : grille, ``taille_invalide``, synthèse.

Petites grilles, relief plat simulé (pas de ``TerrainGenerator``) : rapide.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools.muirfield import run_muirfield as rm
from tools.muirfield.run_muirfield import CalibSize


@pytest.fixture
def flat_output(tmp_path, monkeypatch):
    """Sorties dans ``tmp_path`` et relief plat au-dessus de l'eau."""
    monkeypatch.setattr(rm, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(rm, "load_terrain",
                        lambda seed, width, height: np.full((height, width), 100.0))
    return tmp_path


def test_calib_grid_full_couples_and_orientations():
    sizes = rm.calib_grid()
    couples = {(s.short, s.long) for s in sizes}
    assert len(couples) == 18
    assert len(sizes) == 36
    for size in sizes:
        assert size.short < size.long
        if size.orientation == "portrait":
            assert (size.width, size.height) == (size.short, size.long)
        else:
            assert size.orientation == "paysage"
            assert (size.width, size.height) == (size.long, size.short)


def test_calib_grid_keeps_only_short_below_long_and_filters():
    sizes = rm.calib_grid((300, 400, 450), (400,), ("paysage",))
    assert sizes == [CalibSize(300, 400, "paysage", 400, 300)]


def test_calib_records_taille_invalide_and_writes_summary(flat_output):
    summary = rm.run_calib([CalibSize(200, 400, "portrait", 200, 400)],
                           patterns=("muirfield",), seeds=(1, 2))
    report = json.loads((flat_output / rm.CALIB_DIR / "muirfield_200x400" / "report.json")
                        .read_text(encoding="utf-8"))
    assert report["calib"] == {"short": 200, "long": 400, "orientation": "portrait"}
    assert [r["status"] for r in report["reports"]] == ["taille_invalide"] * 2
    entry = report["reports"][0]
    assert entry["stage"] == "routage"
    assert entry["error_type"] == "ValueError"
    assert "trop petite" in entry["message"]
    row = summary["rows"][0]
    assert row["successes"] == 0 and row["statuses"] == {"taille_invalide": 2}
    assert row["seconds_p90"] is None
    assert not row["ok"] and "taille_invalide" in row["ko_reasons"]
    assert (flat_output / rm.CALIB_DIR / "summary.json").exists()
    assert "taille_invalide" in (flat_output / rm.CALIB_DIR / "summary.md").read_text(
        encoding="utf-8")


def test_size_error_propagates_outside_calib(flat_output):
    with pytest.raises(ValueError, match="trop petite"):
        rm._run_format(200, 400, seeds=(1,), out_name="custom_200x400", planche=False,
                       render=False)


def test_calib_does_not_swallow_unexpected_errors(flat_output, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("bug")

    monkeypatch.setattr(rm, "build_course", boom)
    with pytest.raises(AssertionError):
        rm.run_calib([CalibSize(300, 400, "portrait", 300, 400)], patterns=("muirfield",),
                     seeds=(1,))


def _seed(seed, status="succes", elapsed=1.0, terrain=5.0, violations=0, **extra):
    report = {"seed": seed, "status": status, "elapsed_seconds": elapsed,
              "terrain_seconds_cached_or_built": terrain, "relaunches": 0,
              "attempts": [], "skipped": [], **extra}
    if status == "succes":
        report["violations_total"] = violations
    return report


def _report(pattern, width, height, orientation, seeds):
    short, long = sorted((width, height))
    return {"pattern": pattern, "width": width, "height": height, "width_mode": "variable",
            "calib": {"short": short, "long": long, "orientation": orientation},
            "reports": seeds}


def test_build_calib_summary_rows_aggregates_and_verdicts():
    ok_seeds = [_seed(i, elapsed=0.5 * i) for i in range(1, 7)]
    slow = [_seed(i, elapsed=12.0) for i in range(1, 6)] + [
        _seed(6, status="echec", elapsed=40.0, failure_stages={"oracle": 3})]
    reports = [
        _report("muirfield_inverse", 300, 400, "portrait", ok_seeds),
        _report("muirfield", 300, 400, "portrait", ok_seeds),
        _report("muirfield", 400, 300, "paysage", slow),
    ]
    summary = rm.build_calib_summary(reports)
    rows = summary["rows"]
    assert [(r["orientation"], r["pattern"]) for r in rows] == [
        ("portrait", "muirfield"), ("portrait", "muirfield_inverse"), ("paysage", "muirfield")]
    expected = {"short", "long", "orientation", "pattern", "width", "height", "seeds",
                "successes", "violations_total", "statuses", "failed_seeds",
                "failure_stages", "size_error_messages", "seconds_median", "seconds_p90",
                "seconds_max", "terrain_seconds_mean", "ok", "ko_reasons"}
    assert expected <= set(rows[0])
    assert rows[0]["ok"] and rows[0]["successes"] == 6 and rows[0]["seconds_max"] == 3.0
    assert rows[0]["terrain_seconds_mean"] == 5.0
    bad = rows[2]
    assert bad["successes"] == 5 and bad["failed_seeds"] == [6]
    assert bad["statuses"] == {"echec": 1, "succes": 5}
    assert bad["failure_stages"] == {"oracle": 3}
    assert not bad["ok"]
    assert any(r.startswith("réussites 5/6") for r in bad["ko_reasons"])
    assert any(r.startswith("p90") for r in bad["ko_reasons"])
    assert any(r.startswith("max") for r in bad["ko_reasons"])

    aggregated = {(a["short"], a["long"], a["orientation"]): a for a in summary["aggregated"]}
    portrait = aggregated[(300, 400, "portrait")]
    assert portrait["ok"] and portrait["seeds"] == 12
    assert portrait["successes_by_pattern"] == {"muirfield": 6, "muirfield_inverse": 6}
    landscape = aggregated[(300, 400, "paysage")]
    assert not landscape["ok"]
    assert "muirfield_inverse : non mesuré" in landscape["ko_reasons"]
    assert summary["totals"]["seeds_run"] == 18
    markdown = rm.calib_summary_markdown(summary)
    assert markdown.startswith("# Calibration Muirfield")
    assert "| 300 | 400 | portrait | 300×400 | 6 / 6 |" in markdown


def test_calib_phase2_grid_is_corners_and_centre_in_both_orientations():
    phase = rm.CALIB_PHASE2
    assert phase.directory == "calib_phase2"
    assert phase.seeds == tuple(range(1, 31))
    assert (phase.ok_p90_seconds, phase.ok_max_seconds) == (15.0, 30.0)
    assert set(phase.couples) == {(300, 400), (300, 500), (350, 400), (350, 500), (325, 450)}
    sizes = rm.calib_sizes(phase.couples)
    assert len(sizes) == 10
    assert CalibSize(350, 500, "paysage", 500, 350) in sizes


def test_calib_phase1_unchanged_by_phase_parameter():
    assert rm.CALIB_PHASE1.directory == rm.CALIB_DIR
    assert len(rm.CALIB_PHASE1.couples) == 18
    assert rm.CALIB_PHASE1.ok_p90_seconds == rm.CALIB_OK_P90_SECONDS == 10.0


def test_calib_phase2_verdict_uses_revised_p90():
    seeds = [_seed(i, elapsed=12.0) for i in range(1, 11)]
    reports = [_report(p, 300, 400, "portrait", seeds) for p in rm.CALIB_PATTERNS]
    phase1 = rm.build_calib_summary(reports)
    phase2 = rm.build_calib_summary(reports, rm.CALIB_PHASE2)
    assert not phase1["aggregated"][0]["ok"]
    assert phase2["aggregated"][0]["ok"] and phase2["phase"] == 2
    assert phase2["criterion"]["seconds_p90_max"] == 15.0
    assert rm.calib_summary_markdown(phase2).startswith("# Calibration Muirfield — phase 2")
    assert "p90 ≤ 15 s" in rm.calib_summary_markdown(phase2)


def test_run_calib_phase2_writes_under_its_own_directory(flat_output):
    rm.run_calib([CalibSize(200, 400, "portrait", 200, 400)], patterns=("muirfield",),
                 seeds=(1,), phase=rm.CALIB_PHASE2)
    assert (flat_output / "calib_phase2" / "muirfield_200x400" / "report.json").exists()
    summary = json.loads((flat_output / "calib_phase2" / "summary.json").read_text(
        encoding="utf-8"))
    assert summary["phase"] == 2
    assert not (flat_output / rm.CALIB_DIR).exists()
