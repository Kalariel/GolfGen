"""Prototype de routage global à trous élastiques."""

from experiments.elastic_routing.model import (
    PAR_SPECS,
    SCHEMA_VERSION,
    ControlPoint,
    CourseLayout,
    ElasticHole,
    HoleClassSpec,
    NineLayout,
    WalkingLink,
)
from experiments.elastic_routing.geometry import (
    HoleGeometry,
    ValidationRules,
    Violation,
    build_hole_geometry,
    validate,
)
from experiments.elastic_routing.render import render_svg

__all__ = [
    "PAR_SPECS",
    "SCHEMA_VERSION",
    "ControlPoint",
    "CourseLayout",
    "ElasticHole",
    "HoleGeometry",
    "HoleClassSpec",
    "NineLayout",
    "ValidationRules",
    "Violation",
    "WalkingLink",
    "build_hole_geometry",
    "render_svg",
    "validate",
]
