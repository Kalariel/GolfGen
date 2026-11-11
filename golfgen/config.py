"""Configuration dataclasses pour la génération de parcours de golf."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from golfgen.seed import parse_seed


# Patrons du routeur Muirfield (égal à ``golfgen.routing.muirfield.PATTERN_CHOICES``,
# recopié ici car ``routing`` dépend de ``config`` et jamais l'inverse ; vérifié
# par tests/test_pipeline.py).
COURSE_PATTERNS = ("muirfield", "muirfield_inverse", "random")
ORIENTATIONS = ("landscape", "portrait")
# Styles d'habillage (égal aux clés de ``golfgen.dressing.STYLE_SPECS``, vérifié
# par tests/test_dressing.py). Le style ne change jamais le tracé.
STYLES = ("links", "parkland")
# Bornes des côtés de carte (blocs), issues de la calibration (docs/muirfield-spike.md).
SHORT_SIDE_RANGE = (300, 350)
LONG_SIDE_RANGE = (400, 500)


@dataclass
class TerrainConfig:
    """Paramètres de génération du terrain."""
    octaves: int = 6
    persistence: float = 0.5
    scale: float = 120.0
    elevation_min: int = 58
    elevation_max: int = 82
    base_elevation: int = 64
    central_flat_radius: int = 45
    central_flat_transition: int = 25
    ns_gradient_strength: float = 0.15


@dataclass
class CourseShapeConfig:
    """Patron, style et dimensions de la carte (section JSON ``course``).

    ``landscape`` : largeur = ``long_side``, hauteur = ``short_side`` ;
    ``portrait`` : l'inverse. ``style`` : style d'habillage (``STYLES``),
    sans effet sur le routage."""
    pattern: str = "random"
    style: str = "links"
    orientation: str = "landscape"
    short_side: int = 300
    long_side: int = 400

    def dimensions(self) -> tuple[int, int]:
        """``(width, height)`` de la carte selon l'orientation."""
        if self.orientation == "landscape":
            return self.long_side, self.short_side
        return self.short_side, self.long_side

    def validate(self) -> None:
        """``ValueError`` (message en français) si un champ est hors domaine."""
        self.validate_choices()
        check_sides(self.short_side, self.long_side)

    def validate_choices(self) -> None:
        """``ValueError`` si le patron, le style ou l'orientation est inconnu."""
        if self.pattern not in COURSE_PATTERNS:
            raise ValueError(f"patron inconnu : {self.pattern!r} "
                             f"(attendu : {', '.join(COURSE_PATTERNS)})")
        if self.style not in STYLES:
            raise ValueError(f"style inconnu : {self.style!r} "
                             f"(attendu : {', '.join(STYLES)})")
        if self.orientation not in ORIENTATIONS:
            raise ValueError(f"orientation inconnue : {self.orientation!r} "
                             f"(attendu : {', '.join(ORIENTATIONS)})")


def check_sides(short_side: int, long_side: int) -> None:
    """``ValueError`` si un côté n'est pas un entier dans ses bornes
    (``SHORT_SIDE_RANGE``, ``LONG_SIDE_RANGE``)."""
    for name, value, (lo, hi) in (("petit côté", short_side, SHORT_SIDE_RANGE),
                                  ("grand côté", long_side, LONG_SIDE_RANGE)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} : entier attendu, pas {value!r}")
        if not lo <= value <= hi:
            raise ValueError(f"{name} {value} hors bornes : attendu entre {lo} et {hi} blocs")


@dataclass
class CourseConfig:
    """Configuration complète du parcours.

    ``width``/``height`` sont les dimensions effectives de la carte ; par
    défaut celles de ``course`` (paysage 400×300). ``from_json`` et le
    pipeline les dérivent de ``course``, sauf si elles sont données
    explicitement (alias, exclusifs de l'orientation et des côtés).

    ``seed`` : toujours l'entier signé 64 bits normalisé
    (``golfgen.seed.parse_seed``) ; ``from_json`` résout la saisie du JSON dès
    le chargement, donc aucun texte n'atteint le relief. ``seed_input`` : le
    texte d'origine quand la seed est passée par ``hashCode``, sinon None."""
    width: int = 400
    height: int = 300
    seed: int = 42
    seed_input: Optional[str] = None
    num_holes: int = 18
    total_par: int = 72
    scale_ratio: float = 3.0

    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    course: CourseShapeConfig = field(default_factory=CourseShapeConfig)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, path: str | Path) -> CourseConfig:
        """Charge la config depuis un fichier JSON.

        Dimensions : ``width``/``height`` (alias) OU les clés ``orientation``,
        ``short_side``, ``long_side`` de la section ``course``, jamais les deux
        (``ValueError``). Sans alias, ``width``/``height`` sont dérivées de
        ``course``. Les bornes ne sont pas vérifiées ici (cf. ``validate``).

        ``seed`` est normalisée ici par ``parse_seed`` (``seed_input`` en
        découle) ; une seed ni entière ni texte lève ``ValueError``.

        Une section ``routing`` (paramètres de l'ancien routeur, retiré) est
        ignorée, avec un avertissement sur stderr."""
        with open(path, 'r') as f:
            data = json.load(f)
        if 'routing' in data:
            print(f"{path} : section « routing » ignorée (paramètres de l'ancien "
                  "routeur, sans effet sur le routeur Muirfield)", file=sys.stderr)

        config = cls()

        for key in ('width', 'height', 'num_holes', 'total_par', 'scale_ratio'):
            if key in data:
                setattr(config, key, data[key])

        sub_configs = {
            'terrain': (config.terrain, TerrainConfig),
            'course': (config.course, CourseShapeConfig),
        }
        for section, (obj, _cls) in sub_configs.items():
            if section in data:
                for k, v in data[section].items():
                    if hasattr(obj, k):
                        setattr(obj, k, v)

        try:
            config.seed, config.seed_input = parse_seed(data.get('seed'))
        except TypeError as exc:
            raise ValueError(f"{path} : {exc}") from None

        aliases = [key for key in ('width', 'height') if key in data]
        shape = [key for key in ('orientation', 'short_side', 'long_side')
                 if key in data.get('course', {})]
        if aliases and shape:
            raise ValueError(f"{path} : {'/'.join(aliases)} et course.{'/'.join(shape)} "
                             "sont exclusifs (dimensions données deux fois)")
        if not aliases:
            config.width, config.height = config.course.dimensions()
        return config

    def validate(self) -> None:
        """``ValueError`` si le patron, le style, l'orientation ou les dimensions
        effectives (``width``/``height``) sont hors domaine. À appeler avant
        tout calcul de relief. Les côtés vérifiés sont ceux de la carte
        effective : avec les alias, ``course.short_side``/``long_side`` sont
        ignorés et ``width``/``height`` subissent les mêmes bornes."""
        self.course.validate_choices()
        check_sides(min(self.width, self.height), max(self.width, self.height))

    def save_json(self, path: str | Path) -> None:
        """Sauvegarde la config en JSON."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
