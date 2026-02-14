"""CLI principal — orchestre le pipeline de génération de parcours de golf."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from golfgen.config import CourseConfig
from golfgen.terrain import TerrainGenerator
from golfgen.exporter import JSONExporter


STAGES = ["terrain", "paving", "clubhouse", "routing", "hazards", "vegetation", "features"]


def run_pipeline(config: CourseConfig, stage: str, output: Path) -> None:
    """Exécute le pipeline jusqu'à l'étape indiquée."""
    stage_idx = STAGES.index(stage)
    exporter = JSONExporter(config)

    print(f"Seed: {config.seed} | Taille: {config.width}x{config.height}")
    print(f"Pipeline: {' -> '.join(STAGES[:stage_idx + 1])}")
    print()

    # --- Terrain ---
    t0 = time.time()
    print("1/7  Terrain (Perlin noise)...")
    terrain_gen = TerrainGenerator(config)
    heightmap = terrain_gen.generate()
    exporter.add_terrain(heightmap)
    print(f"     Heightmap {heightmap.shape[1]}x{heightmap.shape[0]}, "
          f"elev [{heightmap.min():.1f}, {heightmap.max():.1f}]  "
          f"({time.time() - t0:.1f}s)")

    if stage_idx < 1:
        exporter.export(output)
        return

    # --- Paving ---
    t0 = time.time()
    print("2/7  Paving (decoupage Voronoi)...")
    from golfgen.paver import PavingGenerator
    paver = PavingGenerator(config, heightmap)
    owner, seeds, cell_sizes = paver.pave()
    pars = config.routing.par_distribution[:config.num_holes]
    print(f"     ({time.time() - t0:.1f}s)")

    if stage_idx < 2:
        exporter.add_paving(owner, seeds, pars)
        exporter.export(output)
        return

    # --- Clubhouse ---
    t0 = time.time()
    print("3/7  Clubhouse (placement optimal)...")
    from golfgen.clubhouse import ClubhousePlacer
    placer = ClubhousePlacer(config, heightmap, owner, seeds, cell_sizes)
    clubhouse_data = placer.place()
    heightmap = placer.heightmap  # heightmap aplatie
    exporter.add_terrain(heightmap)  # re-export terrain modifie
    exporter.add_clubhouse(clubhouse_data)
    print(f"     Clubhouse @ ({config.clubhouse_x}, {config.clubhouse_y})")
    print(f"     Practice: {clubhouse_data['practice_range']['direction']}, "
          f"Putting green: r={clubhouse_data['putting_green']['radius']}  "
          f"({time.time() - t0:.1f}s)")

    # Patch paving : zone 18 clubhouse + remplissage orphelines
    owner = PavingGenerator.patch_owner(
        owner, heightmap, config.paving.tile_size,
        config.paving.water_level, clubhouse_data,
    )
    exporter.add_paving(owner, seeds, pars)

    if stage_idx < 3:
        exporter.export(output)
        return

    # --- Routing (TODO) ---
    print("4/7  Routing — pas encore implemente")
    exporter.export(output)
    return

    # --- Raffinement ---
    t0 = time.time()
    print("5/7  Raffinement terrain + Obstacles...")
    from golfgen.refiner import TerrainRefiner
    from golfgen.hazards import HazardPlacer
    refiner = TerrainRefiner(config)
    heightmap = refiner.refine(heightmap, holes)
    exporter.add_terrain(heightmap)  # Met a jour avec le terrain raffine
    hazard_placer = HazardPlacer(config, heightmap)
    bunkers, water_bodies, ravines = hazard_placer.place(holes)
    exporter.add_hazards(bunkers, water_bodies, ravines)
    print(f"     {len(bunkers)} bunkers, {len(water_bodies)} plans d'eau, "
          f"{len(ravines)} ravins  ({time.time() - t0:.1f}s)")

    if stage_idx < 5:
        exporter.export(output)
        return

    # --- Vegetation ---
    t0 = time.time()
    print("6/7  Vegetation...")
    from golfgen.vegetation import VegetationPainter
    veg_painter = VegetationPainter(config, heightmap)
    tree_clusters, dense_forests = veg_painter.paint(holes)
    exporter.add_vegetation(tree_clusters, dense_forests)
    print(f"     {len(tree_clusters)} clusters, {len(dense_forests)} forets  "
          f"({time.time() - t0:.1f}s)")

    if stage_idx < 6:
        exporter.export(output)
        return

    # --- Features ---
    t0 = time.time()
    print("7/7  Features (ponts, ruisseaux)...")
    from golfgen.features import FeatureGenerator
    feat_gen = FeatureGenerator(config, heightmap)
    features = feat_gen.generate(holes, clubhouse_data)
    exporter.add_features(features)
    print(f"     Features generees  ({time.time() - t0:.1f}s)")

    exporter.export(output)


def main():
    parser = argparse.ArgumentParser(
        description="Generateur procedural de parcours de golf Minecraft"
    )
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed de generation (defaut: 42)")
    parser.add_argument("--stage", choices=STAGES, default="terrain",
                        help="Etape finale du pipeline (defaut: terrain)")
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
