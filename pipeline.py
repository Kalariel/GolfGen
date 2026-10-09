"""CLI principal — orchestre le pipeline de génération de parcours de golf."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from golfgen.config import COURSE_PATTERNS, ORIENTATIONS, CourseConfig
from golfgen.exporter import JSONExporter, muirfield_to_dict, write_json_atomic
from golfgen.seed import parse_seed, seed_u64
from golfgen.terrain import load_or_compute


STAGES = ["terrain", "holes"]
EXIT_ROUTING_FAILED = 2         # aucun parcours valide pour (seed, patron, taille)


def run_pipeline(config: CourseConfig, stage: str, output: Path, *,
                 seed_input: str | None = None) -> int:
    """Exécute le pipeline jusqu'à l'étape indiquée ; renvoie le code de sortie.

    ``config`` doit être résolue et validée (cf. ``resolve_config``) :
    ``config.seed`` est l'entier signé 64 bits. ``holes`` route avec le
    routeur Muirfield et écrit le format 3.0 de façon atomique ; en cas
    d'échec du routage, rien n'est écrit et le code vaut 2."""
    stage_idx = STAGES.index(stage)
    seed = config.seed
    pattern = config.course.pattern

    shown = f"{seed} (« {seed_input} »)" if seed_input is not None else f"{seed}"
    print(f"Seed: {shown} | Taille: {config.width}x{config.height} | Patron: {pattern}")
    print(f"Pipeline: {' -> '.join(STAGES[:stage_idx + 1])}")
    print()

    # --- Terrain (cache unique, clé seed signée + taille + config de relief) ---
    t0 = time.time()
    heightmap, from_cache = load_or_compute(config)
    print(f"1/2  Terrain ({'cached' if from_cache else 'Perlin noise'})...")
    print(f"     Heightmap {heightmap.shape[1]}x{heightmap.shape[0]}, "
          f"elev [{heightmap.min():.1f}, {heightmap.max():.1f}]  "
          f"({time.time() - t0:.1f}s)")

    if stage_idx < 1:
        exporter = JSONExporter(config)
        exporter.add_terrain(heightmap)
        exporter.export(output)
        return 0

    # --- Holes (routeur Muirfield, format 3.0) ---
    from golfgen.routing.muirfield import (MuirfieldRoutingError, build_course,
                                           resolve_pattern)
    t0 = time.time()
    print("2/2  Holes (routeur Muirfield)...")
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

    data = muirfield_to_dict(result, heightmap, seed=int(seed), seed_input=seed_input)
    meta = data["metadata"]
    print(f"     Patron {meta['pattern']['resolved']}, clubhouse "
          f"{data['routing']['clubhouse']['edge']}, {result.relaunches} relance(s)  "
          f"({time.time() - t0:.1f}s)")
    for hole in data["routing"]["holes"]:
        print(f"     #{hole['id']:2d}  {hole['nine']:5s}  par {hole['par']}  "
              f"{hole['length']:6.1f}blocs  "
              f"tee=({hole['tee']['x']:.0f},{hole['tee']['y']:.0f}) "
              f"green=({hole['green']['x']:.0f},{hole['green']['y']:.0f})")

    write_json_atomic(output, data)
    print(f"Export: {output} ({output.stat().st_size / 1024:.1f} Ko, format {meta['version']})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generateur procedural de parcours de golf Minecraft"
    )
    parser.add_argument("--seed", type=str, default=None,
                        help="Seed facon Minecraft Java : entier signe 64 bits, sinon "
                             "texte hache par String.hashCode (defaut : config, 42)")
    parser.add_argument("--stage", choices=STAGES, default="holes",
                        help="Etape finale du pipeline (defaut: holes)")
    parser.add_argument("--config", type=str, default=None,
                        help="Fichier de configuration JSON")
    parser.add_argument("--output", type=str, default="output/course.json",
                        help="Fichier de sortie JSON")
    parser.add_argument("--pattern", choices=COURSE_PATTERNS, default=None,
                        help="Patron du parcours (defaut : config, random)")
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
    entier signé, et ``seed_input`` (texte haché, sinon None)."""
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

    raw = args.seed if args.seed not in (None, "") else config.seed
    try:
        config.seed, seed_input = parse_seed(raw)
    except TypeError as exc:
        raise ValueError(str(exc)) from None
    return config, seed_input


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config, seed_input = resolve_config(args)
    except ValueError as exc:
        # Même code (2) et même forme qu'une erreur d'argparse.
        parser.error(str(exc))

    output = Path(args.output)

    print("=" * 50)
    print("  GOLF COURSE GENERATOR")
    print("=" * 50)
    print()

    t_total = time.time()
    code = run_pipeline(config, args.stage, output, seed_input=seed_input)
    if code == 0:
        print()
        print(f"Termine en {time.time() - t_total:.1f}s")
    return code


if __name__ == "__main__":
    sys.exit(main())
