"""Normalisation commune des JSON avant calcul des empreintes figées
(``tests/test_pipeline.py``, ``tests/test_dressing_paths_frozen.py``,
``tests/test_dressing_trees_frozen.py``)."""

from __future__ import annotations

import copy

# valeur au relevé des empreintes, ne pas suivre __version__
FROZEN_GENERATOR = "golfgen 0.1.0"


def normalize_frozen(data: dict) -> dict:
    """Copie de ``data`` avec ``metadata.stats.elapsed_seconds`` à 0 (seul champ
    qui dépend de l'horloge) et ``metadata.generator`` ramené à
    ``FROZEN_GENERATOR`` (seul champ qui dépend de la version)."""
    data = copy.deepcopy(data)
    data["metadata"]["stats"]["elapsed_seconds"] = 0.0
    data["metadata"]["generator"] = FROZEN_GENERATOR
    return data
