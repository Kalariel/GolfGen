"""Planche du rendu du rough (``tools.dressing.rough_plate``, R5b) : partie
sans navigateur — eau, masques, mesures des trous, choix et recadrage."""

from __future__ import annotations

import base64
import json
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from tools.dressing import rough_plate as rp

W, H = 60, 40


def _square(x0, y0, x1, y1):
    return [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]


def _hole(hole_id, y, *, fairway, tee_x=5.0, width=6.0):
    return {
        "id": hole_id, "par": 4, "width": width, "rough_margin": 2.0,
        "tee": {"x": tee_x, "y": y}, "green": {"x": 50.0, "y": y}, "doglegs": [],
        "features": {
            "tees": [{"outline": _square(tee_x - 2, y - 1.5, tee_x + 2, y + 1.5)}],
            **({} if fairway is None else {"fairway": fairway}),
        },
    }


@pytest.fixture
def course():
    # relief : octet 255 partout, 0 (eau) sur x 30..34, y 0..14
    raw = np.full((H, W), 255, dtype=np.uint8)
    raw[0:15, 30:35] = 0
    holes = [
        # trou 1 (y = 8) : traverse l'eau, deux morceaux de part et d'autre
        _hole(1, 8.0, fairway=[{"outline": _square(15, 6, 29, 10)},
                               {"outline": _square(36, 6, 46, 10)}]),
        # trou 2 (y = 16) : bande de jeu qui chevauche celle du trou 1, un peu d'eau dans le cœur,
        # long carry (fairway à partir de x = 30)
        _hole(2, 16.0, fairway=[{"outline": _square(30, 14, 46, 18)}]),
        # trou 3 (y = 30) : fairway vidé
        _hole(3, 30.0, fairway=[]),
        # trou 4 (y = 37) : fichier d'avant R5 (pas de clé fairway)
        _hole(4, 37.0, fairway=None, width=2.0),
    ]
    return {
        "terrain": {"width": W, "height": H, "water_level": 10.0,
                    "elevation": {"min_elevation": 0.0, "max_elevation": 100.0,
                                  "data": base64.b64encode(raw.tobytes()).decode()}},
        "routing": {"holes": holes},
    }


def test_water_mask_uses_viewer_threshold(course):
    water = rp.water_mask(course)
    assert water.shape == (H, W)
    assert water.sum() == 15 * 5 and water[0:15, 30:35].all()
    del course["terrain"]["water_level"]
    assert not rp.water_mask(course).any()


def test_polygon_mask_counts_cell_centres():
    mask = rp.polygon_mask([(2, 3), (7, 3), (7, 5), (2, 5)], 10, 10)
    assert mask.sum() == 10 and mask[3:5, 2:7].all()


def test_hole_tags(course):
    tags = {t.id: t for t in rp.hole_tags(course)}
    assert tags[1].pieces == 2 and tags[1].core_water > 0
    assert tags[3].pieces == 0 and tags[3].empty and tags[3].carry is None
    assert tags[4].pieces is None and not tags[4].empty
    # sommets contre sommets : boîte avant (x = 7, y ± 1,5) -> fairway (y ± 2)
    assert tags[2].carry == pytest.approx(30 - 7, abs=0.1)
    assert tags[1].carry == pytest.approx(15 - 7, abs=0.1)
    assert tags[2].overlap_with == 1 and tags[2].overlap_cells > 0
    assert tags[1].core_water > tags[2].core_water > 0


def test_select_holes_one_per_criterion(course):
    chosen = rp.select_holes(rp.hole_tags(course))
    reasons = dict(chosen)
    assert reasons[1] == "fairway coupé par l'eau"
    assert reasons[2] == "carry de rough après les départs"
    assert reasons[3] == "bandes de jeu voisines qui se chevauchent"  # vidé, mais déjà pris
    assert 4 not in reasons
    assert len({i for i, _ in chosen}) == len(chosen) <= rp.MAX_HOLES
    assert len(rp.select_holes(rp.hole_tags(course), max_holes=2)) == 2


def test_crop_view_centres_padded_box():
    zoom, pan_x, pan_y = rp.crop_view((10, 20, 50, 40), tile_w=480, tile_h=360, pad=5)
    assert zoom == pytest.approx(min(480 / 50, 360 / 30))
    # le centre de la boîte tombe au centre de la vignette
    assert 30 * zoom + pan_x == pytest.approx(240)
    assert 30 * zoom + pan_y == pytest.approx(180)
    # la boîte élargie tient entière dans la vignette
    assert 5 * zoom + pan_x >= -1e-9 and 55 * zoom + pan_x <= 480 + 1e-9
    assert 15 * zoom + pan_y >= -1e-9 and 45 * zoom + pan_y <= 360 + 1e-9


def test_band_polygon_matches_core_plus_margin(course):
    hole = course["routing"]["holes"][0]
    x0, y0, x1, y1 = rp.bbox(rp.band_polygon(hole))
    # bouts tee et green prolongés du rayon (buffered_axis)
    assert (x0, y0, x1, y1) == pytest.approx((5 - 5, 8 - 5, 50 + 5, 8 + 5))
    cx0, cy0, cx1, cy1 = rp.bbox(rp.core_polygon(hole))
    assert (cx0, cy0, cx1, cy1) == pytest.approx((2, 5, 53, 11))


def test_overview_size_keeps_map_ratio():
    assert rp.overview_size(400, 300, 640, pad=4) == (640, round(640 * 308 / 408))
    w, h = rp.overview_size(300, 400, 640, pad=0)
    assert (w, h) == (640, 853)
    zoom, pan_x, pan_y = rp.crop_view((0, 0, 300, 400), w, h, pad=0)
    assert pan_x == pytest.approx(0, abs=1) and pan_y == pytest.approx(0, abs=1)


def test_parse_holes_validates_ids(course):
    known = {t.id: t for t in rp.hole_tags(course)}
    assert rp.parse_holes("3,1", known) == [(3, "imposé"), (1, "imposé")]
    with pytest.raises(SystemExit, match="absent"):
        rp.parse_holes("1,19", known)
    with pytest.raises(SystemExit, match="mal formé"):
        rp.parse_holes("1,,2", known)


def test_seeds_report_helpers():
    # --seeds : non posés lus dans la console du pipeline, posés dans le JSON 3.2
    stdout = ("4/4  Bunkers (trous vides : per_hole)  (9.8s)\n"
              "     30 posé(s) : haricot/green 12, pot/landing 18 ; trou(s) vide(s) : #7\n"
              "     3 non posé(s) : construction/map 1, green/no_legal_flank 2\n")
    assert rp.parse_unplaced(stdout) == (3, {"construction/map": 1, "green/no_legal_flank": 2})
    assert rp.parse_unplaced("     0 non posé(s)\n") == (0, {})
    assert rp.parse_unplaced("sans bunkers\n") == (None, {})
    data = {"metadata": {"width": 400, "height": 300, "pattern": {"resolved": "muirfield"}},
            "routing": {"holes": [{"id": i} for i in (1, 2, 3, 7)]},
            "bunkers": {"empty_holes": [7], "items": [
                {"family": "pot", "role": "landing", "hole": 1}, {"family": "pot", "role": "landing", "hole": 1},
                {"family": "haricot", "role": "green", "hole": 2}]}}
    assert rp.bunker_counts(data) == {"placed": 3, "empty_holes": [7], "holes_without_bunker": [3, 7],
                                      "by_family_role": {"haricot/green": 1, "pot/landing": 2},
                                      "by_family": {"haricot": 1, "pot": 2}}
    assert rp.bunker_counts({"metadata": {}}) is None
    assert rp.seed_title(5, data) == "seed 5 — 400x300, muirfield"


def _item(hole, ident, family, cells, status="construction", role="green"):
    return {"id": ident, "hole": hole, "family": family, "role": role, "status": status, "cells": cells}


@pytest.mark.parametrize("argv, message", [
    (["--seeds", "1-2", "--width", "400"], "--width et --height"),
    (["--seed", "1", "--style", "links", "--height", "300"], "--width et --height"),
    (["--seeds", "1-2", "--holes", "3"], "--holes : avec --seed seulement"),
    (["--seeds", "1-2", "--tile", "640x480", "--overview"], "--tile, --overview : avec --seed seulement"),
    (["--seeds", "1-2", "--copy-to", "x"], "--copy-to : avec --seed seulement"),
    (["--seed", "1", "--style", "links", "--overview-width", "800"], "--overview-width : avec --seeds"),
    (["--seeds", "1-2", "--compare-organics"], "unrecognized arguments: --compare-organics"),
    (["--seeds", "1-2", "--no-organics"], "unrecognized arguments: --no-organics"),
    (["--seed", "1"], "--style requis"),
])
def test_rejected_option_combinations(argv, message, monkeypatch, capsys):
    monkeypatch.setattr(rp, "require_magick", lambda: pytest.fail("vérification après magick"))
    with pytest.raises(SystemExit) as exc:
        rp.main(argv)
    assert exc.value.code == 2
    assert message in capsys.readouterr().err


def test_run_seed_passes_pipeline_options(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 3, "", "Pose impossible\n")

    monkeypatch.setattr(rp.subprocess, "run", fake_run)
    args = SimpleNamespace(style=None, pattern=None, width=400, height=300)
    record, path = rp.run_seed(args, 5, tmp_path)
    assert path is None and record["exit_code"] == 3 and record["error"] == "Pose impossible"
    assert calls[0][-4:] == ["--width", "400", "--height", "300"]
    assert str(tmp_path / "seed_5.json") in calls[0]
    assert not [arg for arg in calls[0] if "organi" in arg]


class _Server:
    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


def _offline(monkeypatch, tmp_path, shot):
    """``seeds_batch`` sans navigateur ni magick : seed 2 capturée par
    ``shot``, toutes les seeds avec un JSON écrit."""
    def fake_run_seed(args, seed, output):
        path = output / f"seed_{seed}.json"
        items = [_item(1, "pot_green_1", "pot", [[0, 0]]), _item(2, "haricot_green_1", "haricot", [[9, 8]], "flanc")]
        path.write_text(json.dumps({"metadata": {"width": 40, "height": 30, "pattern": {"resolved": "random"}},
                                    "terrain": {"width": 40, "height": 30},
                                    "routing": {"holes": [{"id": 1}, {"id": 2}]},
                                    "bunkers": {"empty_holes": [], "items": items}}), encoding="utf-8")
        record = {"seed": seed, "exit_code": 0, "pipeline_seconds": 0.0, "size": "40x30", "pattern": "random",
                  "bunkers": None, "unplaced": None}
        return record, path

    def touch(path, *args, **kwargs):
        path.write_bytes(b"png")
        return path

    monkeypatch.setattr(rp, "find_chrome", lambda explicit: tmp_path / "chrome")
    monkeypatch.setattr(rp, "start_server", lambda port: _Server())
    monkeypatch.setattr(rp, "run_seed", fake_run_seed)
    monkeypatch.setattr(rp, "overview_shot", shot)
    monkeypatch.setattr(rp, "_text_tile", lambda path, *args, **kwargs: touch(path))
    monkeypatch.setattr(rp, "_stack", lambda paths, path, **kwargs: touch(path))
    monkeypatch.setattr(rp, "montage", lambda paths, path: touch(path))
    return SimpleNamespace(output=tmp_path, chrome=None, overview_width=200, style=None, pattern=None,
                           width=None, height=None)


def test_capture_failure_does_not_stop_the_batch(monkeypatch, tmp_path):
    def shot(chrome, port, json_path, size, view, path):
        if "seed_2" in path.name:
            raise rp.CaptureError("capture vide")
        return path.write_bytes(b"png") and path

    args = _offline(monkeypatch, tmp_path, shot)
    plate, failed = rp.seeds_batch(args, (1, 2, 3))
    assert failed == [2] and plate == tmp_path / "montage.png"
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["failed_seeds"] == [2]
    runs = {r["seed"]: r for r in report["runs"]}
    assert runs[2]["error"] == "capture : capture vide" and "png" not in runs[2]
    assert runs[1]["png"] == "seed_1.png" and runs[3]["png"] == "seed_3.png"


@pytest.mark.parametrize("failed, code", [([], 0), ([7], rp.EXIT_SEEDS_FAILED)])
def test_exit_code_reflects_failed_seeds(failed, code, monkeypatch):
    monkeypatch.setattr(rp, "require_magick", lambda: None)
    outputs = []
    monkeypatch.setattr(rp, "seeds_batch", lambda args, seeds: outputs.append(args.output) or (None, failed))
    assert rp.main(["--seeds", "7"]) == code
    assert outputs == [rp.SEEDS_OUTPUT_DIR]
