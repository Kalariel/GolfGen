import xml.etree.ElementTree as ET

from experiments.elastic_routing.geometry import ValidationRules
from experiments.elastic_routing.render import render_svg
from experiments.elastic_routing.synthetic import build_synthetic_layout
from tests.test_elastic_routing_geometry import _stack


def test_render_produces_parseable_svg_with_course_semantics():
    layout = build_synthetic_layout(seed=42)
    rules = ValidationRules(
        link_max=500.0,
        max_parallel_stack=None,
        clubhouse_clear_radius=0.0,
        walkable_links=False,
    )
    svg = render_svg(layout, rules)

    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")
    assert "VALIDE · seed 42" in svg
    assert "H1/p3" in svg
    assert "H18/p3" in svg
    assert "bleu=par3" in svg


def test_render_lists_and_highlights_invalid_holes():
    # Depuis l'étape 2b (cliques maximales au lieu des composantes connexes),
    # le layout synthétique ne contient plus de pile parallèle fautive (voir
    # tests/test_elastic_routing_geometry.py pour le détail) : seuls
    # link_distance et link_blocked restent attendus ici.
    svg = render_svg(build_synthetic_layout(), ValidationRules())

    assert "INVALIDE" in svg
    assert "link_distance:" in svg
    assert "link_blocked:" in svg
    assert 'stroke="#ff2d7a"' in svg


def test_render_highlights_parallel_stack_violation():
    # Réutilise la fixture clique de 4 trous de test_elastic_routing_geometry
    # (étape 2b) : le layout synthétique seul ne couvre plus parallel_stack
    # depuis le passage aux cliques maximales (décompte 4 -> 0), donc le
    # rendu doit être vérifié sur un layout qui contient une vraie clique.
    layout = _stack(build_synthetic_layout(), (2, 3, 4, 5),
                     (-100.0, -94.0, -88.0, -82.0))
    svg = render_svg(layout, ValidationRules())

    assert "INVALIDE" in svg
    assert "parallel_stack:" in svg
    assert 'stroke="#ff2d7a"' in svg
