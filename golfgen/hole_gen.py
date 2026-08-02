"""Distribution des pars du parcours (patron corrigé automatiquement)."""

from __future__ import annotations

from golfgen.config import CourseConfig


def resolve_par_distribution(config: CourseConfig) -> list[int]:
    """Retourne une distribution valide, proche de la configuration.

    ``par_distribution`` est traitee comme un patron prefere. Si sa somme ne
    correspond pas a ``total_par``, une programmation dynamique choisit les
    changements minimaux, puis favorise un aller/retour equilibre.
    """
    n = config.num_holes
    target = config.total_par
    if n < 1:
        raise ValueError("num_holes doit etre strictement positif")
    if not 3 * n <= target <= 5 * n:
        raise ValueError(
            f"total_par={target} impossible pour {n} trous (attendu entre {3*n} et {5*n})"
        )

    preferred = list(config.routing.par_distribution[:n])
    preferred.extend([4] * (n - len(preferred)))
    invalid = [p for p in preferred if p not in (3, 4, 5)]
    if invalid:
        raise ValueError(f"pars invalides dans par_distribution: {invalid}")

    # Etat: (somme totale, somme aller) -> (cout de modification, distribution)
    mid = n // 2
    states: dict[tuple[int, int], tuple[int, tuple[int, ...]]] = {(0, 0): (0, ())}
    for idx, wanted in enumerate(preferred):
        remaining = n - idx - 1
        next_states: dict[tuple[int, int], tuple[int, tuple[int, ...]]] = {}
        for (total, front), (cost, values) in states.items():
            for par in (3, 4, 5):
                new_total = total + par
                if new_total + 3 * remaining > target or new_total + 5 * remaining < target:
                    continue
                new_front = front + par if idx < mid else front
                candidate = (cost + (par != wanted), values + (par,))
                key = (new_total, new_front)
                current = next_states.get(key)
                if current is None or candidate < current:
                    next_states[key] = candidate
        states = next_states

    solutions = [
        (cost, abs(2 * front - target), values)
        for (total, front), (cost, values) in states.items()
        if total == target
    ]
    if not solutions:
        raise ValueError(f"aucune distribution de pars possible pour {n} trous et par {target}")

    # Changements minimaux d'abord, equilibre aller/retour ensuite, puis ordre
    # lexicographique pour garantir un resultat totalement deterministe.
    _, _, result = min(solutions)
    return list(result)


