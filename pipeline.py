"""CLI principal — orchestre le pipeline de génération de parcours de golf."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator
from golfgen.exporter import JSONExporter


STAGES = ["terrain", "holes"]


def run_pipeline(config: CourseConfig, stage: str, output: Path) -> None:
    """Exécute le pipeline jusqu'à l'étape indiquée."""
    stage_idx = STAGES.index(stage)
    exporter = JSONExporter(config)

    print(f"Seed: {config.seed} | Taille: {config.width}x{config.height}")
    print(f"Pipeline: {' -> '.join(STAGES[:stage_idx + 1])}")
    print()

    # --- Terrain (cached by seed) ---
    t0 = time.time()
    cache_dir = Path("output/.cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    terrain_cache = cache_dir / f"terrain_s{config.seed}_{config.width}x{config.height}.npy"
    
    import numpy as np
    if terrain_cache.exists():
        print("1/2  Terrain (cached)...")
        heightmap = np.load(terrain_cache)
    else:
        print("1/2  Terrain (Perlin noise)...")
        terrain_gen = TerrainGenerator(config)
        heightmap = terrain_gen.generate()
        np.save(terrain_cache, heightmap)
    
    exporter.add_terrain(heightmap)
    print(f"     Heightmap {heightmap.shape[1]}x{heightmap.shape[0]}, "
          f"elev [{heightmap.min():.1f}, {heightmap.max():.1f}]  "
          f"({time.time() - t0:.1f}s)")

    if stage_idx < 1:
        exporter.export(output)
        return

    # --- Holes (génération + placement + séquençage) ---
    t0 = time.time()
    print("2/2  Holes (skeletons + packing + sequencing)...")
    from golfgen.course_builder import build_course
    holes, clubhouse_pos = build_course(config, heightmap)

    exporter.add_routing(holes, clubhouse_pos=clubhouse_pos)
    print(f"     {len(holes)} trous places  ({time.time() - t0:.1f}s)")

    for h in holes:
        print(f"     #{h['id']:2d}  par {h['par']}  {h['blocks']:3d}blocs  "
              f"dir={h['direction']:2s}  "
              f"tee=({h['tee']['x']:.0f},{h['tee']['y']:.0f}) "
              f"green=({h['green']['x']:.0f},{h['green']['y']:.0f})")

    exporter.export(output)


def main():
    parser = argparse.ArgumentParser(
        description="Generateur procedural de parcours de golf Minecraft"
    )
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed de generation (defaut: 42)")
    parser.add_argument("--stage", choices=STAGES, default="holes",
                        help="Etape finale du pipeline (defaut: holes)")
    parser.add_argument("--config", type=str, default=None,
                        help="Fichier de configuration JSON")
    parser.add_argument("--output", type=str, default="output/course.json",
                        help="Fichier de sortie JSON")
    parser.add_argument("--width", type=int, default=None,
                        help="Largeur du terrain en blocs")
    parser.add_argument("--height", type=int, default=None,
                        help="Hauteur du terrain en blocs")

    args = parser.parse_args()

    # Charger config
    if args.config:
        config = CourseConfig.from_json(args.config)
    else:
        config_path = Path("default_config.json")
        if config_path.exists():
            config = CourseConfig.from_json(config_path)
        else:
            config = CourseConfig()

    # Surcharges CLI
    if args.seed is not None:
        config.seed = args.seed
    if args.width is not None:
        config.width = args.width
    if args.height is not None:
        config.height = args.height

    output = Path(args.output)

    print("=" * 50)
    print("  GOLF COURSE GENERATOR")
    print("=" * 50)
    print()

    t_total = time.time()
    run_pipeline(config, args.stage, output)
    print()
    print(f"Termine en {time.time() - t_total:.1f}s")


if __name__ == "__main__":
    main()
