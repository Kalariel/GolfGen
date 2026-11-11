"""Profil en long du fairway (lot 2 R3) et contournement des obstacles,
appliqués PAR-DESSUS la forme brute (``golfgen.dressing.fairway`` : en
production, B v1 à col marqué ``profile_neck``, R2b ; B v1 ``profile_b`` sur
demande, ``raw_profile``), branchés à ``dress_course`` (champ ``profiled_field``,
coupé sur l'eau par ``golfgen.dressing.fairway_water.water_fairway`` ;
``fairway_shapes`` : même fairway sans eau).

Profil en long (``build_profiled_fairway``), appliqué PAR-DESSUS la forme
brute, dans le profil de largeur le long de l'axe, avant la ligne de niveau
(mêmes tirages de forme, même plafond : le fairway reste dans le cœur sans
clip) :

- étendue (``fairway_span``) : de ``TEE_MARGIN`` devant l'avant de la boîte
  la plus avancée (plus le carry de rough tiré, ou, au par 3 avec
  ``PAR3_CARRY_TO_APRON``, ``par3_fairway`` blocs seulement devant le
  green) jusqu'à ``END_WRAP`` après le front du green ; bouts en quart
  d'ellipse (``START_NOSE``, ``END_NOSE``) ;
- jonction au green : entrée ouverte (largeur gardée jusqu'au green) ou
  avant-green resserré (homothétie vers ``apron_width`` sur
  ``apron_length`` + ``APRON_RAMP`` blocs) ;
- contournement (``clear_obstacles``) dans le champ : ``max(champ, marge −
  distance signée)`` autour du green, des greens doubles (``GreenPair.outline``)
  et des boîtes de départ, de tous les trous (``fairway_obstacles``) ;
  ``GREEN_MARGIN`` / ``TEE_MARGIN``. Pourquoi dans le champ plutôt que dans
  le profil : un green (haricot, recul, green double qui déborde de côté)
  n'est pas une fonction de ``s`` ; le profil seul ne garantirait pas
  l'écart. Pourquoi pas un découpage du polygone a posteriori : une seule
  ligne de niveau, un seul contour, et une boucle coupée en deux reste
  détectée (``DressingError``, jamais réparée en silence). Le profil porte
  donc l'essentiel (début, fin, resserrement lisse), la garde n'ajoute que
  l'épousage du front du green et le contournement des doubles.

Coupure sur l'eau : R4, ``golfgen.dressing.fairway_water`` (dans le champ
de ``profiled_field``, avant la ligne de niveau).

Contour : ligne de niveau 0 du champ (``fairway.strip_field`` puis
contournement), rééchantillonnée au pas ``OUTLINE_STEP`` ; îlots d'un nœud
de grille retirés et comptés (``fairway.fairway_outline``) ; ``fairway_shapes``
lève ``DressingError`` s'il n'y a pas exactement une boucle réelle. Écart aux
obstacles : tout nœud de grille dans le fairway est à plus que la marge ;
la ligne de niveau, interpolée au pas ``GRID_STEP``, puis le contour
rééchantillonné (cordes de ``OUTLINE_STEP``) peuvent passer un peu en
deçà ; bornes explicites et dérivation : ``grid_gap_bound`` et
``outline_gap_bound`` (``tests/test_dressing_fairway.py``).

Aléa : flux ``golfgen.dressing.course.fairway_profile_rng`` (``[seed,
RNG_LABEL, order, PROFILE_STREAM]``, 4), séparé de celui de la forme
(``fairway_rng``, 3, mêmes tirages que ``build_fairway``, quelle que soit la
forme brute) ; six tirages
toujours faits dans le même ordre (``long_profile``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from golfgen.dressing.fairway import (BIG, GRID_STEP, Axis, FairwayBuild, FairwayStyle,
                                      Grid, Profile, RawProfile, _smoothstep, cap_half,
                                      fairway_outline, profile_neck, strip_field)
from golfgen.dressing.green import shoelace
from golfgen.dressing.model import DressingError, FairwayShape
from golfgen.dressing.offset import grid_signed_distance
from golfgen.routing.model import ElasticHole


# --- profil en long (R3) ---------------------------------------------------------------
#
# Constantes PROVISOIRES (planches du profil en long, R3).

TEE_MARGIN = 2.0                # blocs : rough entre l'avant de la boîte la plus avancée
                                # et le bout du fairway ; garde autour de toute boîte
GREEN_MARGIN = 1.0              # blocs : garde autour du green (green double compris)
START_NOSE = 5.0                # blocs : bout arrondi (quart d'ellipse) côté départ
END_NOSE = 3.0                  # blocs : idem côté green
END_WRAP = 2.0                  # blocs : le profil dépasse le front du green d'autant,
                                # la garde GREEN_MARGIN le contourne (jonction épousée)
APRON_RAMP = 10.0               # blocs : raccord smoothstep vers la largeur d'avant-green
MIN_FAIRWAY = 10.0              # blocs : longueur minimale, le carry est réduit en deçà
OUTSIDE = -1.0                  # demi-largeur hors de l'étendue du fairway (champ > 0)
NOSE_SAMPLES = 17               # points ajoutés à la table du profil par bout
# Option visible (planches) : au par 3, le carry va jusqu'à l'avant-green
# (seuls ``ProfileStyle.par3_fairway`` blocs de fairway gardés devant le
# green) ; ``False`` : carry ordinaire de ``ProfileStyle.carry[0]``.
PAR3_CARRY_TO_APRON = True
PARS = (3, 4, 5)


@dataclass(frozen=True, slots=True)
class ProfileStyle:
    """Profil en long d'un style, plages et parts PROVISOIRES (blocs) ;
    tuples indexés par par (3, 4, 5)."""

    name: str
    carry_share: tuple[float, float, float]     # P(carry de rough après les départs)
    carry: tuple[tuple[float, float], ...]      # longueur du carry
    par3_fairway: tuple[float, float]           # par 3, carry jusqu'à l'avant-green :
                                                # fairway gardé devant le front du green
    apron_share: float                          # P(avant-green resserré), sinon entrée ouverte
    apron_width: tuple[float, float]            # largeur de l'avant-green
    apron_length: tuple[float, float]           # longueur resserrée devant le front du green


PROFILE_STYLES: Mapping[str, ProfileStyle] = MappingProxyType({
    # links : fairway plus souvent continu, entrée de green ouverte (jeu roulé)
    "links": ProfileStyle("links", carry_share=(0.45, 0.35, 0.35),
                          carry=((6.0, 14.0), (8.0, 20.0), (10.0, 24.0)),
                          par3_fairway=(10.0, 18.0), apron_share=0.30,
                          apron_width=(6.0, 7.5), apron_length=(8.0, 14.0)),
    # parkland : carry plus fréquent et plus long, avant-green resserré plus fréquent
    "parkland": ProfileStyle("parkland", carry_share=(0.70, 0.60, 0.60),
                             carry=((8.0, 16.0), (12.0, 26.0), (14.0, 30.0)),
                             par3_fairway=(8.0, 14.0), apron_share=0.60,
                             apron_width=(5.5, 7.0), apron_length=(10.0, 16.0)),
})


@dataclass(frozen=True, slots=True)
class LongProfile:
    """Choix du profil en long d'un trou (``long_profile``) : carry de rough
    après les départs (sinon continu), avant-green resserré (sinon entrée
    ouverte) ; ``carry_length`` : longueur du carry, ou, au par 3 avec
    ``PAR3_CARRY_TO_APRON``, du fairway gardé devant le green."""

    carry: bool
    apron: bool
    carry_length: float
    apron_width: float
    apron_length: float
    to_apron: bool = False      # par 3 : carry jusqu'à l'avant-green


def long_profile(rng: np.random.Generator, par: int, style: ProfileStyle, *,
                 carry: bool | None = None, apron: bool | None = None) -> LongProfile:
    """Tirages du profil en long, toujours tous et dans le même ordre (flux
    ``fairway_profile_rng``) : deux uniformes (carry, avant-green), longueur
    du carry du par, fairway gardé du par 3, largeur puis longueur de
    l'avant-green. ``carry`` / ``apron`` forcent le choix (planches)."""
    if par not in PARS:
        raise ValueError(f"par inattendu : {par!r}")
    k = par - 3
    u_carry, u_apron = rng.random(2)
    carry_length = rng.uniform(*style.carry[k])
    par3_fairway = rng.uniform(*style.par3_fairway)
    width = rng.uniform(*style.apron_width)
    length = rng.uniform(*style.apron_length)
    to_apron = par == 3 and PAR3_CARRY_TO_APRON
    return LongProfile(
        carry=bool(u_carry < style.carry_share[k]) if carry is None else carry,
        apron=bool(u_apron < style.apron_share) if apron is None else apron,
        carry_length=float(par3_fairway if to_apron else carry_length),
        apron_width=float(width), apron_length=float(length), to_apron=to_apron)


def tee_front(axis: Axis, tees) -> float:
    """Abscisse de l'avant de la boîte la plus avancée (sommets projetés sur
    le premier segment, où sont toutes les boîtes) ; 0 sans boîte."""
    points = [p for box in tees for p in box.outline]
    if not points:
        return 0.0
    along = (np.asarray(points, dtype=float) - axis.points[0]) @ axis.tangents[0]
    return float(max(along.max(), 0.0))


def green_front(axis: Axis, green_outline) -> float:
    """Abscisse du front du green (sommets projetés sur le dernier segment)."""
    along = (np.asarray(green_outline, dtype=float) - axis.points[-2]) @ axis.tangents[-1]
    return float(axis.starts[-1] + along.min())


@dataclass(frozen=True)
class Span:
    """Étendue du fairway sur l'axe : ``start`` (bout côté départ), ``end``
    (bout côté green, ``green + END_WRAP`` au plus), ``green`` (front du
    green), ``carry`` (rough au-delà de ``TEE_MARGIN``, 0 sans carry),
    ``clamped`` (carry tiré mais plus court que visé, jusqu'à 0 compris :
    ``fairway_span``)."""

    start: float
    end: float
    green: float
    carry: float
    clamped: bool


def fairway_span(axis: Axis, plan: LongProfile, s_tee: float, s_green: float) -> Span:
    """Étendue du fairway, départs à ``s_tee`` (avant de la boîte la plus
    avancée), front du green à ``s_green``. Début visé : ``TEE_MARGIN``
    devant les départs (continu), plus ``carry_length`` (carry), ou
    ``carry_length`` devant le green (par 3 jusqu'à l'avant-green) ; puis
    borné à ``[TEE_MARGIN devant les départs, end − MIN_FAIRWAY]``. Tout
    carry tiré qui n'atteint pas ce début visé est ``clamped`` : réduit pour
    garder ``MIN_FAIRWAY`` (jusqu'à 0 si la place manque), ou nul au par 3
    quand le fairway gardé devant le green déborde sur les départs ; jamais
    réduit en silence."""
    first = s_tee + TEE_MARGIN
    end = min(s_green + END_WRAP, axis.length)
    if not plan.carry:
        wanted = first
    elif plan.to_apron:
        wanted = s_green - plan.carry_length
    else:
        wanted = first + plan.carry_length
    start = max(first, min(wanted, end - MIN_FAIRWAY))
    clamped = bool(plan.carry and start != wanted)
    return Span(float(start), float(end), float(s_green), float(start - first), clamped)


def _nose(x: np.ndarray) -> np.ndarray:
    """Quart d'ellipse : 0 en 0, 1 en 1, tangente verticale en 0."""
    x = np.clip(x, 0.0, 1.0)
    return np.sqrt(1.0 - (1.0 - x) ** 2)


def apply_long_profile(raw: Profile, span: Span, plan: LongProfile) -> Profile:
    """Profil brut ``raw`` restreint à ``span`` : avant-green (si tiré) par
    homothétie de chaque côté, de rapport ``largeur d'avant-green / largeur
    avant bruit`` (le bruit est réduit d'autant, sans plancher qui
    l'aplatirait), atteint en ``APRON_RAMP`` (smoothstep) à
    ``apron_length`` du front du green ; bouts en quart
    d'ellipse sur ``START_NOSE`` / ``END_NOSE`` ; ``OUTSIDE`` hors de
    l'étendue. Les demi-largeurs ne font que baisser : le fairway reste dans
    le cœur."""
    length = span.end - span.start
    n_start, n_end = min(START_NOSE, length / 3.0), min(END_NOSE, length / 3.0)
    t = np.linspace(0.0, 1.0, NOSE_SAMPLES)
    extra = np.concatenate((span.start + n_start * t, span.end - n_end * t))
    s = np.union1d(raw.s, extra[(extra >= raw.s[0]) & (extra <= raw.s[-1])])
    left, right, base = (np.interp(s, raw.s, v) for v in (raw.left, raw.right, raw.base))
    if plan.apron:
        weight = _smoothstep((s - (span.green - plan.apron_length - APRON_RAMP)) / APRON_RAMP)
        ratio = np.minimum(plan.apron_width / 2.0 / base, 1.0)
        factor = 1.0 - weight * (1.0 - ratio)
        left, right = left * factor, right * factor
    inside = (s >= span.start) & (s <= span.end)
    envelope = _nose((s - span.start) / n_start) * _nose((span.end - s) / n_end)
    return Profile(s, np.where(inside, left * envelope, OUTSIDE),
                   np.where(inside, right * envelope, OUTSIDE), raw.zones, raw.plateaus, base)


# --- contournement --------------------------------------------------------------------

@dataclass(frozen=True)
class Obstacle:
    """Polygone que le fairway contourne à ``margin`` au moins. ``kind`` :
    ``"green"``, ``"paire"`` (green double) ou ``"departs"`` ; ``owners`` :
    trous dont c'est le green, la paire ou les boîtes (pour un autre trou,
    l'obstacle est rapporté ``"voisin"``) ; ``lo`` / ``hi`` : cadre du
    polygone élargi de ``margin``."""

    kind: str
    owners: frozenset[int]
    outline: np.ndarray
    margin: float
    lo: np.ndarray
    hi: np.ndarray

    @classmethod
    def of(cls, kind: str, owners, outline, margin: float) -> Obstacle:
        outline = np.asarray(outline, dtype=float)
        return cls(kind, frozenset(owners), outline, margin,
                   outline.min(axis=0) - margin, outline.max(axis=0) + margin)


def fairway_obstacles(holes, pairs=()) -> tuple[Obstacle, ...]:
    """Obstacles des fairways d'un parcours, calculés une fois : green et
    boîtes de chaque trou (``{order: HoleDressing}``), contour de chaque
    green double (``GreenPair.outline``)."""
    out = []
    for order, hd in holes.items():
        out.append(Obstacle.of("green", (order,), hd.green.outline, GREEN_MARGIN))
        out.extend(Obstacle.of("departs", (order,), box.outline, TEE_MARGIN)
                   for box in hd.tees)
    out.extend(Obstacle.of("paire", (pair.i, pair.j), pair.outline, GREEN_MARGIN)
               for pair in pairs if pair.outline)
    return tuple(out)


def clear_obstacles(field: np.ndarray, grid: Grid, obstacles, order: int) -> tuple[str, ...]:
    """Contournement dans le champ, avant la ligne de niveau : ``field ←
    max(field, margin − d)``, ``d`` = distance signée au polygone (négative
    dedans, ``golfgen.dressing.offset.grid_signed_distance``, exacte dans la
    bande utile), sur la fenêtre de grille de l'obstacle ; obstacles hors du
    cadre de la grille, ou dont la fenêtre ne touche pas le fairway, sautés.
    Renvoie, dans l'ordre, les sortes d'obstacles (``"voisin"`` s'il n'est
    pas au trou ``order``) qui ont mordu le fairway (un nœud intérieur rendu
    extérieur)."""
    bitten = []
    pad = 2.0 * GRID_STEP
    lo_grid = (grid.xs[0], grid.ys[0])
    hi_grid = (grid.xs[-1], grid.ys[-1])
    for obstacle in obstacles:
        lo, hi = obstacle.lo, obstacle.hi
        if (lo[0] > hi_grid[0] or lo[1] > hi_grid[1]
                or hi[0] < lo_grid[0] or hi[1] < lo_grid[1]):
            continue
        rows, cols = grid.window(lo - pad, hi + pad)
        if rows.start >= rows.stop or cols.start >= cols.stop:
            continue
        window = field[rows, cols]
        if not (window < 0.0).any():
            continue
        distance = grid_signed_distance(grid.xs[cols], grid.ys[rows], obstacle.outline,
                                        band=obstacle.margin + pad)
        clear = np.minimum(obstacle.margin - distance, BIG)
        if ((window < 0.0) & (clear >= 0.0)).any():
            bitten.append(obstacle.kind if order in obstacle.owners else "voisin")
        np.maximum(window, clear, out=window)
    return tuple(bitten)


# --- fairway d'un trou -----------------------------------------------------------------

@dataclass(frozen=True)
class ProfiledField:
    """Champ du fairway profilé et contourné, avant la ligne de niveau
    (``build_profiled_fairway`` ; les tests y mesurent la ligne brute)."""

    field: np.ndarray
    grid: Grid
    profile: Profile
    plan: LongProfile
    span: Span
    bitten: tuple[str, ...]


def profiled_field(hole: ElasticHole, core, style: FairwayStyle,
                   rng: np.random.Generator, profile_rng: np.random.Generator,
                   tees, green_outline, obstacles=(), *,
                   carry: bool | None = None, apron: bool | None = None,
                   raw_profile: RawProfile = profile_neck) -> ProfiledField:
    """Champ de ``build_profiled_fairway`` (mêmes arguments), avant la ligne
    de niveau ; ``raw_profile`` : forme brute (production ``profile_neck`` ;
    ``fairway.profile_b`` pour B v1, planches)."""
    axis = Axis.of(hole)
    cap = cap_half(hole)
    grid = Grid.around(core)
    raw = raw_profile(hole, axis, style, rng, cap)
    plan = long_profile(profile_rng, hole.par, PROFILE_STYLES[style.name],
                        carry=carry, apron=apron)
    span = fairway_span(axis, plan, tee_front(axis, tees), green_front(axis, green_outline))
    profile = apply_long_profile(raw, span, plan)
    field = strip_field(axis, profile, grid, cap)
    bitten = clear_obstacles(field, grid, obstacles, hole.order)
    return ProfiledField(field, grid, profile, plan, span, bitten)


def build_profiled_fairway(hole: ElasticHole, core, style: FairwayStyle,
                           rng: np.random.Generator, profile_rng: np.random.Generator,
                           tees, green_outline, obstacles=(), *,
                           carry: bool | None = None, apron: bool | None = None,
                           raw_profile: RawProfile = profile_neck) -> FairwayBuild:
    """Forme brute ``raw_profile`` (production : B v1 à col marqué
    ``profile_neck`` ; mêmes tirages que ``build_fairway``, flux ``rng``) avec
    le profil en long (R3, flux ``profile_rng``) : étendue de ``TEE_MARGIN``
    (plus le carry) devant les boîtes ``tees`` jusqu'au front de
    ``green_outline`` (plus ``END_WRAP``), avant-green ; puis contournement
    des ``obstacles`` (``fairway_obstacles`` du parcours) dans le champ.
    ``carry`` / ``apron`` forcent les
    choix (planches). Contour : ``fairway.fairway_outline`` (îlots sous la
    résolution retirés, comptés dans ``FairwayBuild.islands``)."""
    built = profiled_field(hole, core, style, rng, profile_rng, tees, green_outline, obstacles,
                           carry=carry, apron=apron, raw_profile=raw_profile)
    outline, loops, islands = fairway_outline(built.field, built.grid)
    return FairwayBuild(outline, loops, built.profile, built.plan, built.span, built.bitten,
                        islands)


def fairway_shapes(hole: ElasticHole, core, style: FairwayStyle, rng: np.random.Generator,
                   profile_rng: np.random.Generator, tees, green_outline,
                   obstacles=()) -> tuple[FairwayShape, ...]:
    """Polygone du fairway du trou SANS eau (``build_profiled_fairway`` ;
    ``dress_course`` le coupe sur l'eau par
    ``fairway_water.water_fairway``, qui le redonne au bit près sans eau à
    portée), coordonnées NON arrondies. Lève
    ``DressingError`` si la ligne de niveau n'a pas exactement une boucle
    réelle, aucune comprise (seuls les îlots d'un nœud de grille,
    ``fairway.is_island``, sont retirés, explicitement et comptés ; un
    contournement qui coupe le fairway en deux est rapporté, pas réparé)."""
    build = build_profiled_fairway(hole, core, style, rng, profile_rng, tees, green_outline,
                                   obstacles)
    if build.loops != 1:
        raise DressingError(f"trou {hole.order} : fairway en {build.loops} boucles "
                            f"(une seule attendue, style {style.name})")
    outline = tuple((x, y) for x, y in build.outline.tolist())
    return (FairwayShape(outline=outline, area=float(shoelace(build.outline))),)
