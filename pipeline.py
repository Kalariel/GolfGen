"""CLI principal — orchestre le pipeline de génération de parcours de golf."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from golfgen.config import COURSE_PATTERNS, ORIENTATIONS, STYLES, CourseConfig
from golfgen.exporter import (muirfield_to_dict, with_bunkers, with_dressing, with_paths,
                              with_trees, write_json_atomic)
from golfgen.seed import java_trim, parse_seed, seed_u64
from golfgen.terrain import ReliefExportError, load_or_compute


EXIT_BAD_PARAMETER = 2          # paramètre invalide (code d'argparse)
EXIT_ROUTING_FAILED = 3         # aucun parcours valide pour (seed, patron, taille)
                                # ou habillage/bunkers impossibles (même consigne : autre seed)
                                # ou chemins impossibles (PathError : un bogue, même code)
                                # ou arbres impossibles (TreeError : un bogue, même code)


def _bunkers_lines(course_bunkers) -> list[str]:
    """Lignes de l'étape bunkers : posés par famille/rôle, trous vides, non
    posés (CLI seulement, absents du JSON) par étape/raison."""
    summary = course_bunkers.summary()
    placed = ", ".join(f"{key} {n}" for key, n in sorted(summary["by_family_role"].items()))
    empty = ", ".join(f"#{order}" for order in summary["empty_holes"]) or "aucun"
    lines = [f"     {summary['placed']} posé(s) : {placed or '-'} ; trou(s) vide(s) : {empty}"]
    reasons = ", ".join(f"{key} {n}" for key, n in sorted(summary["unplaced_by_reason"].items()))
    lines.append(f"     {summary['unplaced']} non posé(s)" + (f" : {reasons}" if reasons else ""))
    return lines


def _paths_line(course_paths, seconds: float, steps: int = 5) -> str:
    """Ligne de l'étape chemins : largeur, cases (ponts), parvis, ancrages,
    raccords de l'union et, s'il y en a, contacts par un coin restés sans
    case de raccord libre (``union_defects``, aucun attendu)."""
    debug = course_paths.debug
    plaza = (f"parvis {course_paths.plaza.size}" if course_paths.plaza is not None
             else "sans parvis")
    laid = sum(lp.status != "trivial" for lp in debug.links)
    defects = (f", {len(debug.union_defects)} contact(s) non raccordé(s)"
               if debug.union_defects else "")
    return (f"5/{steps}  Chemins (largeur {course_paths.width:g}) : {laid} liaison(s), "
            f"{len(course_paths.cells)} cases dont {len(course_paths.bridge_cells)} de pont, "
            f"{plaza}, {len(course_paths.anchors)} ancrage(s), "
            f"{len(debug.union_added)} raccord(s){defects}  ({seconds:.1f}s)")


def _trees_line(course_trees, margin: float, seconds: float, steps: int) -> str:
    """Ligne de l'étape arbres : total, arbres par couche, sauts par motif."""
    layers = ", ".join(f"{name} {n}" for name, n in course_trees.counts.items())
    skips = ", ".join(f"{name} {motif} {n}" for name, motifs in course_trees.skips.items()
                      for motif, n in motifs.items()) or "aucun"
    return (f"{steps}/{steps}  Arbres (marge {margin:g}) : {len(course_trees.items)} posé(s) ({layers}) ; "
            f"sauts : {skips}  ({seconds:.1f}s)")


def run_pipeline(config: CourseConfig, output: Path, *,
                 seed_input: str | None = None, bunkers: bool = True,
                 paths: bool | None = None, paths_debug: bool = False,
                 trees: bool | None = None, tree_margin: float | None = None,
                 trees_debug: bool = False) -> int:
    """Exécute le pipeline complet (relief, parcours, habillage, bunkers,
    chemins, arbres) ; renvoie le code de sortie.

    ``config`` doit être résolue et validée (cf. ``resolve_config``) :
    ``config.seed`` est l'entier signé 64 bits. Le relief passe par le cache
    (``load_or_compute``), le parcours par le routeur Muirfield, exporté en
    JSON 3.0 ; l'habillage relit ce seul JSON (``dress_course_json``, style
    ``config.course.style``, flux aléatoire propre : sans effet sur le tracé)
    et ``with_dressing`` en fait le 3.1 ; les bunkers (``bunkers``, défaut
    vrai : ``place_bunkers_json``, même JSON, même habillage, eau réelle,
    trous vides par trou) en font le 3.2 (``with_bunkers``, clé
    ``bunkers``) ; sans eux, le 3.1 d'avant. Les chemins (``paths``,
    défaut : ``bunkers`` ; ``place_paths`` sur ce JSON 3.2) en font le 3.3
    (``with_paths``, clé ``paths``, détail par liaison avec
    ``paths_debug``) ; sans eux, le 3.2 d'avant, à l'octet près. Versions
    en escalier : pas de chemins sans bunkers (``ValueError``). Les arbres
    (``trees``, défaut : ``paths`` ; ``place_trees`` sur ce JSON 3.3, marge
    ``tree_margin``, défaut 5, détail avec ``trees_debug``) en font le 3.4
    (``with_trees``, clé ``trees``) ; sans eux, le 3.3 d'avant, à l'octet
    près. Pas d'arbres sans chemins (``ValueError``).
    ``output`` le reçoit, écrit
    de façon atomique ; en cas d'échec du routage, de son export (relief
    non exportable sans perte), de la relecture du JSON (``CourseJsonError``)
    de l'habillage (``DressingError``) ou de la pose des bunkers
    (``BunkerError`` de ``place_bunkers_json`` : géométrie impossible pour
    cette seed ; autre seed ou ``--no-bunkers``) ou du tracé des chemins
    (``PathError`` de ``place_paths`` : une liaison sans route ou coupée,
    un bogue par construction ; même code que les bunkers, pour qu'un appelant qui
    balaie les seeds passe à la suivante, mais message explicite : « bogue
    du tracé », ``--no-paths`` pour contourner) ou de la pose des arbres
    (``TreeError`` : un bogue, même traitement, ``--no-trees``), rien n'est écrit et le
    code vaut ``EXIT_ROUTING_FAILED`` (3) ; toute autre exception est un
    bogue et remonte."""
    if paths is None:
        paths = bunkers
    if paths and not bunkers:
        raise ValueError("chemins sans bunkers : versions en escalier (3.3 = 3.2 + chemins)")
    if paths_debug and not paths:
        raise ValueError("détail des chemins demandé sans chemins")
    if trees is None:
        trees = paths
    if trees and not paths:
        raise ValueError("arbres sans chemins : versions en escalier (3.4 = 3.3 + arbres)")
    if trees_debug and not trees:
        raise ValueError("détail des arbres demandé sans arbres")
    if tree_margin is not None:
        if not trees:
            raise ValueError("marge des arbres demandée sans arbres")
        from golfgen.dressing.trees.course import validate_margin
        validate_margin(tree_margin)
    seed = config.seed
    pattern = config.course.pattern
    style = config.course.style
    steps = 6 if trees else 5 if paths else 4 if bunkers else 3

    shown = f"{seed} (« {seed_input} »)" if seed_input is not None else f"{seed}"
    print(f"Seed: {shown} | Taille: {config.width}x{config.height} | Patron: {pattern} "
          f"| Style: {style}")
    print()

    # --- Terrain (cache unique, clé seed signée + taille + config de relief) ---
    t0 = time.time()
    heightmap, from_cache = load_or_compute(config)
    print(f"1/{steps}  Terrain ({'cached' if from_cache else 'Perlin noise'})...")
    print(f"     Heightmap {heightmap.shape[1]}x{heightmap.shape[0]}, "
          f"elev [{heightmap.min():.1f}, {heightmap.max():.1f}]  "
          f"({time.time() - t0:.1f}s)")

    # --- Holes (routeur Muirfield) ---
    from golfgen.routing.muirfield import (MuirfieldRoutingError, build_course,
                                           resolve_pattern)
    t0 = time.time()
    print(f"2/{steps}  Holes (routeur Muirfield)...")
    numpy_seed = seed_u64(seed)
    try:
        result = build_course(numpy_seed, pattern, heightmap,
                              width=config.width, height=config.height)
    except MuirfieldRoutingError:
        resolved = resolve_pattern(numpy_seed, pattern)
        label = resolved if resolved == pattern else f"{resolved} (tiré au sort)"
        print(f"Aucun parcours valide pour la seed {seed} (patron {label}, "
              f"{config.width}x{config.height}) : essayez une autre seed.", file=sys.stderr)
        return EXIT_ROUTING_FAILED

    print(f"     Patron {result.pattern}, clubhouse {result.clubhouse_edge}, "
          f"{result.relaunches} relance(s)  ({time.time() - t0:.1f}s)")

    # --- Habillage : étape 2, depuis le seul JSON 3.0 de l'étape 1 (sans
    # re-router ; même habillage, au bit près, qu'en mémoire) ---
    from golfgen.dressing import CourseJsonError, DressingError, dress_course_json
    try:
        routed = muirfield_to_dict(result, heightmap, seed=int(seed), seed_input=seed_input)
    except ReliefExportError as exc:
        # relief non exportable sans perte (``relief_f32_block``) : le JSON ne
        # suffirait pas à l'habillage ; toute autre ``ValueError`` de l'export
        # (incohérence interne) remonte
        print(f"Export du routage impossible pour la seed {seed} : {exc}. "
              "Aucun fichier écrit.", file=sys.stderr)
        return EXIT_ROUTING_FAILED
    t0 = time.perf_counter()
    try:
        dressing = dress_course_json(routed, style)
    except CourseJsonError as exc:
        print(f"JSON du routage non habillable pour la seed {seed} : {exc}. "
              "Aucun fichier écrit.", file=sys.stderr)
        return EXIT_ROUTING_FAILED
    except DressingError as exc:
        print(f"Habillage impossible pour la seed {seed} (style {style}) : {exc}. "
              "Aucun fichier écrit ; essayez une autre seed.", file=sys.stderr)
        return EXIT_ROUTING_FAILED
    reduced = sum(hole.green.reduced for hole in dressing.holes.values())
    print(f"3/{steps}  Habillage (style {style}) : 18 greens, {reduced} réduit(s) par le cœur  "
          f"({(time.perf_counter() - t0) * 1000:.0f} ms)")
    counts = [len(hole.tees) for hole in dressing.holes.values()]
    fallbacks = sum(hole.tee_fallback_cause is not None for hole in dressing.holes.values())
    print(f"     Départs : {sum(counts)} boîtes ; trous à 1/2/3 boîtes : "
          f"{counts.count(1)}/{counts.count(2)}/{counts.count(3)} ; "
          f"{fallbacks} bascule(s)")

    data = with_dressing(routed, dressing)
    for hole in data["routing"]["holes"]:
        print(f"     #{hole['id']:2d}  {hole['nine']:5s}  par {hole['par']}  "
              f"{hole['length']:6.1f}blocs  "
              f"tee=({hole['tee']['x']:.0f},{hole['tee']['y']:.0f}) "
              f"green=({hole['green']['x']:.0f},{hole['green']['y']:.0f}) "
              f"{hole['features']['green']['area']:.0f}blocs²")

    if bunkers:
        # --- Bunkers : même principe, depuis le JSON du routage et
        # l'habillage (eau réelle, seed du routage ; sans re-router) ---
        from golfgen.dressing.bunkers import BunkerError, place_bunkers_json
        t0 = time.perf_counter()
        try:
            course_bunkers = place_bunkers_json(routed, dressing)
        except CourseJsonError as exc:
            print(f"JSON du routage non lisible par la pose des bunkers pour la seed {seed} : "
                  f"{exc}. Aucun fichier écrit.", file=sys.stderr)
            return EXIT_ROUTING_FAILED
        except BunkerError as exc:
            # géométrie dépendante de la seed (enveloppe dégénérée, empreinte
            # sans sable, trou sans fairway…) : même consigne que l'habillage,
            # rien n'est écrit ; toute autre exception (bogue) remonte
            print(f"Pose des bunkers impossible pour la seed {seed} (style {style}) : {exc}. "
                  "Aucun fichier écrit ; essayez une autre seed ou --no-bunkers.",
                  file=sys.stderr)
            return EXIT_ROUTING_FAILED
        print(f"4/{steps}  Bunkers (trous vides : {course_bunkers.empty_rule})  "
              f"({time.perf_counter() - t0:.1f}s)")
        for line in _bunkers_lines(course_bunkers):
            print(line)
        data = with_bunkers(data, course_bunkers)

    if paths:
        # --- Chemins : depuis le JSON 3.2 de l'étape précédente (scène,
        # parvis, liaisons, virages ; sans re-router) ---
        from golfgen.dressing.paths import PathError, place_paths
        t0 = time.perf_counter()
        try:
            course_paths = place_paths(data)
        except CourseJsonError as exc:
            print(f"JSON non lisible par le tracé des chemins pour la seed {seed} : {exc}. "
                  "Aucun fichier écrit.", file=sys.stderr)
            return EXIT_ROUTING_FAILED
        except PathError as exc:
            # une liaison sans route ou coupée : impossible par construction, donc un
            # bogue, rendu explicite ; rien n'est écrit
            print(f"Tracé des chemins impossible pour la seed {seed} (style {style}) : {exc}. "
                  "Bogue du tracé, aucun fichier écrit ; --no-paths pour s'en passer.",
                  file=sys.stderr)
            return EXIT_ROUTING_FAILED
        print(_paths_line(course_paths, time.perf_counter() - t0, steps))
        data = with_paths(data, course_paths, debug=paths_debug)

    if trees:
        # --- Arbres : depuis le JSON 3.3 de l'étape précédente et sa scène
        # (déjà construite pour les chemins ; sans re-router) ---
        from golfgen.dressing.trees import CORRIDOR_MARGIN, TreeError, place_trees
        margin = CORRIDOR_MARGIN if tree_margin is None else tree_margin
        t0 = time.perf_counter()
        try:
            course_trees = place_trees(data, margin, scene=course_paths.debug.scene)
        except CourseJsonError as exc:
            print(f"JSON non lisible par la pose des arbres pour la seed {seed} : {exc}. "
                  "Aucun fichier écrit.", file=sys.stderr)
            return EXIT_ROUTING_FAILED
        except TreeError as exc:
            # invariant cassé : un bogue, jamais un échec attendu (trous sautés et
            # ancrages partiels sont comptés) ; rien n'est écrit
            print(f"Pose des arbres interrompue pour la seed {seed} (style {style}) : {exc}. "
                  "Bogue de la pose, aucun fichier écrit ; --no-trees pour s'en passer.",
                  file=sys.stderr)
            return EXIT_ROUTING_FAILED
        print(_trees_line(course_trees, margin, time.perf_counter() - t0, steps))
        data = with_trees(data, course_trees, debug=trees_debug)

    write_json_atomic(output, data)
    print(f"Export: {output} ({output.stat().st_size / 1024:.1f} Ko, format {data['metadata']['version']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generateur procedural de parcours de golf Minecraft",
        epilog=f"Codes de sortie : 0 succes, {EXIT_BAD_PARAMETER} parametre invalide, "
               f"{EXIT_ROUTING_FAILED} aucun parcours valide pour la seed (essayer "
               "une autre seed ; chemins : bogue du trace, --no-paths ; "
               "arbres : bogue de la pose, --no-trees)."
    )
    parser.add_argument("--seed", type=str, default=None,
                        help="Seed facon Minecraft Java : blancs de tete et de queue "
                             "retires, puis entier signe 64 bits, sinon texte hache par "
                             "String.hashCode ; vide : defaut (config, 42)")
    parser.add_argument("--config", type=str, default=None,
                        help="Fichier de configuration JSON")
    parser.add_argument("--output", type=str, default="output/course.json",
                        help="Fichier de sortie JSON")
    parser.add_argument("--pattern", choices=COURSE_PATTERNS, default=None,
                        help="Patron du parcours (defaut : config, random)")
    parser.add_argument("--style", choices=STYLES, default=None,
                        help="Style d'habillage, sans effet sur le trace "
                             "(defaut : config, links)")
    parser.add_argument("--no-bunkers", action="store_true",
                        help="Sans bunkers (ni chemins, ni arbres) : JSON 3.1 sans cles "
                             "bunkers, paths ni trees (defaut : bunkers, chemins et arbres, JSON 3.4)")
    parser.add_argument("--no-paths", action="store_true",
                        help="Sans chemins (ni arbres) : JSON 3.2 sans cles paths ni trees "
                             "(defaut : chemins poses, JSON 3.4)")
    parser.add_argument("--paths-debug", action="store_true",
                        help="Detail des chemins par liaison dans paths.debug "
                             "(trace, statut, pont, cases ; exclusif de --no-paths/--no-bunkers)")
    parser.add_argument("--no-trees", action="store_true",
                        help="Sans arbres : JSON 3.3 sans cle trees (defaut : arbres poses, JSON 3.4)")
    parser.add_argument("--tree-margin", type=float, default=None,
                        help="Marge en blocs du corridor de lisiere et de remplissage, 0 a 12 "
                             "(defaut : 5 ; exclusif de --no-trees/--no-paths/--no-bunkers)")
    parser.add_argument("--trees-debug", action="store_true",
                        help="Compteurs et bosquets dans trees.debug "
                             "(exclusif de --no-trees/--no-paths/--no-bunkers)")
    parser.add_argument("--orientation", choices=ORIENTATIONS, default=None,
                        help="landscape : largeur = grand cote ; portrait : l'inverse "
                             "(defaut : config, landscape)")
    parser.add_argument("--short", type=int, default=None,
                        help="Petit cote en blocs, 300 a 350 (defaut : config, 300)")
    parser.add_argument("--long", type=int, default=None,
                        help="Grand cote en blocs, 400 a 500 (defaut : config, 400)")
    parser.add_argument("--width", type=int, default=None,
                        help="Alias : largeur en blocs (exclusif de --orientation/--short/--long)")
    parser.add_argument("--height", type=int, default=None,
                        help="Alias : hauteur en blocs (exclusif de --orientation/--short/--long)")
    return parser


def resolve_config(args: argparse.Namespace) -> tuple[CourseConfig, str | None]:
    """Config effective (fichier, puis surcharges CLI), validée.

    Lève ``ValueError`` (message en français) pour tout paramètre invalide,
    AVANT tout calcul de relief. Renvoie la config avec ``seed`` résolue en
    entier signé, et ``seed_input`` (texte haché, sinon None). ``--seed``
    vide ou blanc garde la seed de la config, déjà normalisée par
    ``CourseConfig.from_json``."""
    if args.config:
        config = CourseConfig.from_json(args.config)
    else:
        config_path = Path("default_config.json")
        if config_path.exists():
            config = CourseConfig.from_json(config_path)
        else:
            config = CourseConfig()

    aliases = [f"--{name}" for name in ("width", "height") if getattr(args, name) is not None]
    shape = [f"--{name}" for name in ("orientation", "short", "long")
             if getattr(args, name) is not None]
    if aliases and shape:
        raise ValueError(f"{'/'.join(aliases)} et {'/'.join(shape)} sont exclusifs : "
                         "donner soit la largeur/hauteur, soit l'orientation et les côtés")

    if args.pattern is not None:
        config.course.pattern = args.pattern
    if args.style is not None:
        config.course.style = args.style
    if shape:
        if args.orientation is not None:
            config.course.orientation = args.orientation
        if args.short is not None:
            config.course.short_side = args.short
        if args.long is not None:
            config.course.long_side = args.long
        config.course.validate()
        config.width, config.height = config.course.dimensions()
    if args.width is not None:
        config.width = args.width
    if args.height is not None:
        config.height = args.height
    config.validate()

    if args.seed is not None and java_trim(args.seed) != "":
        config.seed, config.seed_input = parse_seed(args.seed)
    return config, config.seed_input


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.paths_debug and (args.no_paths or args.no_bunkers):
            raise ValueError("--paths-debug demande les chemins : incompatible avec "
                             "--no-paths et --no-bunkers")
        without_trees = args.no_trees or args.no_paths or args.no_bunkers
        if args.trees_debug and without_trees:
            raise ValueError("--trees-debug demande les arbres : incompatible avec "
                             "--no-trees, --no-paths et --no-bunkers")
        if args.tree_margin is not None:
            if without_trees:
                raise ValueError("--tree-margin demande les arbres : incompatible avec "
                                 "--no-trees, --no-paths et --no-bunkers")
            from golfgen.dressing.trees.course import validate_margin
            validate_margin(args.tree_margin)
        config, seed_input = resolve_config(args)
    except ValueError as exc:
        # Même code (EXIT_BAD_PARAMETER = 2) et même forme qu'une erreur d'argparse.
        parser.error(str(exc))

    output = Path(args.output)

    print("=" * 50)
    print("  GOLF COURSE GENERATOR")
    print("=" * 50)
    print()

    t_total = time.time()
    # --no-bunkers implique --no-paths (pas de chemins sans bunkers) et
    # --no-paths implique --no-trees (pas d'arbres sans chemins)
    code = run_pipeline(config, output, seed_input=seed_input, bunkers=not args.no_bunkers,
                        paths=not (args.no_bunkers or args.no_paths),
                        paths_debug=args.paths_debug, trees=not without_trees,
                        tree_margin=args.tree_margin, trees_debug=args.trees_debug)
    if code == 0:
        print()
        print(f"Termine en {time.time() - t_total:.1f}s")
    return code


if __name__ == "__main__":
    sys.exit(main())
