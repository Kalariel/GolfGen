from experiments.bean_paving.bean_bank import BeanTemplate, _footprint
from experiments.bean_paving.geometry import PlacedBean, Transform, ValidationRules
from experiments.bean_paving.pack_then_route import PackingResult, PackingState, route_packing


def _bean(name):
    axis = ((0.0, 0.0), (10.0, 0.0))
    return BeanTemplate(name, 4, 10.0, axis, 2.0, 0.0, _footprint(axis, 1.0),
                        axis[0], axis[-1], 0.0, 0.0)


def test_route_graph_uses_port_distances_independently_of_packing_order():
    placed = (
        PlacedBean(_bean("a"), Transform(50, 50), 1),
        PlacedBean(_bean("b"), Transform(80, 50), 2),
        PlacedBean(_bean("c"), Transform(110, 50), 3),
    )
    packing = PackingResult(1, PackingState(placed, 0.0), (), (), {},
                            ValidationRules(width=160, height=100))
    routing = route_packing(packing)
    assert (0, 1) in routing.edges
    assert (1, 2) in routing.edges
    assert len(routing.longest_path) == 3
    assert 0 in routing.start_nodes
