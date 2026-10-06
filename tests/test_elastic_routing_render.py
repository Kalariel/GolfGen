import xml.etree.ElementTree as ET

from experiments.elastic_routing.geometry import ValidationRules
from experiments.elastic_routing.render import render_svg
from experiments.elastic_routing.synthetic import build_synthetic_layout


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
    # Depuis l'étape 2b (séries de trous consécutifs côte à côte au lieu des
    # cliques maximales), le layout synthétique retrouve ses 4 piles
    # parallèles fautives (voir tests/test_elastic_routing_geometry.py pour
    # le détail) : parallel_stack, link_distance et link_blocked sont tous
    # attendus ici.
    svg = render_svg(build_synthetic_layout(), ValidationRules())

    assert "INVALIDE" in svg
    assert "link_distance:" in svg
    assert "link_blocked:" in svg
    assert "parallel_stack:" in svg
    assert 'stroke="#ff2d7a"' in svg
