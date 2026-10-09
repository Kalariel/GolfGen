"""Génération de terrain par Perlin noise (OpenSimplex), et son cache disque."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

import numpy as np
import opensimplex

from .config import CourseConfig, TerrainConfig


# Cache unique du relief (pipeline et routeur Muirfield) : chemin absolu,
# indépendant du répertoire courant ; ``output/.cache/`` est ignoré par git.
TERRAIN_CACHE_DIR = Path(__file__).resolve().parents[1] / "output" / ".cache" / "terrain"
TERRAIN_CACHE_VERSION = 1      # à incrémenter si TerrainGenerator change d'algorithme


def terrain_cache_tag(terrain: TerrainConfig | None = None) -> str:
    """Empreinte de la configuration de relief : version + hash de ``TerrainConfig``.
    Toute modification des paramètres de relief invalide donc le cache."""
    payload = json.dumps({"version": TERRAIN_CACHE_VERSION,
                          "terrain": asdict(terrain or TerrainConfig())}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def terrain_cache_path(config: CourseConfig, cache_dir: Path | None = None) -> Path:
    """Fichier ``.npy`` du relief de ``config`` : seed, taille et ``terrain_cache_tag``."""
    directory = Path(cache_dir) if cache_dir is not None else TERRAIN_CACHE_DIR
    return directory / (f"terrain_s{config.seed}_{config.width}x{config.height}"
                        f"_{terrain_cache_tag(config.terrain)}.npy")


def load_or_generate(config: CourseConfig, cache_dir: Path | None = None) -> np.ndarray:
    """Relief de ``TerrainGenerator(config).generate()``, mis en cache sur disque
    (cf. ``load_or_compute``, dont il ne garde que le relief).

    Returns:
        np.ndarray float32 de shape (height, width), identique à
        ``TerrainGenerator(config).generate()``.
    """
    return load_or_compute(config, cache_dir)[0]


def load_or_compute(config: CourseConfig,
                    cache_dir: Path | None = None) -> tuple[np.ndarray, bool]:
    """Relief de ``TerrainGenerator(config).generate()`` et sa provenance.

    Seul point d'entrée du cache de relief, partagé par ``pipeline.py`` et le
    routeur Muirfield. Le relief ne dépend que de la seed, de la taille et de
    ``config.terrain`` : la clé (cf. ``terrain_cache_path``) couvre exactement
    ces trois éléments. ``cache_dir`` vaut ``TERRAIN_CACHE_DIR`` par défaut.
    Un fichier en cache dont la shape n'est pas (height, width) est ignoré :
    le relief est recalculé et le remplace (message sur stderr).
    L'écriture est atomique (fichier temporaire du même dossier puis
    ``os.replace``) : un lecteur concurrent ne voit jamais un fichier partiel.

    Returns:
        ``(heightmap, from_cache)`` : float32 de shape (height, width) ;
        ``from_cache`` vaut True si et seulement si le relief renvoyé est
        celui lu sur disque.
    """
    path = terrain_cache_path(config, cache_dir)
    expected = (config.height, config.width)
    try:
        cached = np.load(path)
    except FileNotFoundError:
        cached = None
    if cached is not None:
        if cached.shape == expected:
            return cached, True
        print(f"Cache de relief {path.name} : shape {cached.shape}, attendu {expected} ; "
              "relief recalculé et cache remplacé.", file=sys.stderr)
    heightmap = TerrainGenerator(config).generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Nom unique ouvert en "xb" (et non mkstemp, en 0600) : droits usuels du umask.
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "xb") as handle:
            np.save(handle, heightmap)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return heightmap, False


class TerrainGenerator:
    """Génère une heightmap via OpenSimplex multi-octave."""

    def __init__(self, config: CourseConfig):
        self.config = config
        self.tc = config.terrain

    def generate(self) -> np.ndarray:
        """Génère la heightmap (float32, valeurs en élévation Minecraft).

        Returns:
            np.ndarray de shape (height, width) avec des valeurs dans
            [elevation_min, elevation_max].
        """
        w, h = self.config.width, self.config.height
        raw = self._multi_octave_noise(w, h)
        raw = self._apply_ns_gradient(raw, h)
        # _apply_central_flat retiré — fait par l'étape clubhouse
        heightmap = self._normalize(raw)
        return heightmap

    def _multi_octave_noise(self, w: int, h: int) -> np.ndarray:
        """Bruit OpenSimplex multi-octave (vectorisé).

        ``opensimplex.seed`` ramène la seed sur 64 bits signés (``ctypes.c_int64``) :
        une seed signée et son complément à deux u64 donnent le même bruit, une
        seed négative est donc acceptée telle quelle."""
        opensimplex.seed(self.config.seed)

        # Coordonnées de la grille
        xs = np.arange(w, dtype=np.float64)
        ys = np.arange(h, dtype=np.float64)

        result = np.zeros((h, w), dtype=np.float64)
        amplitude = 1.0
        frequency = 1.0
        max_amplitude = 0.0

        for _ in range(self.tc.octaves):
            scaled_x = xs * frequency / self.tc.scale
            scaled_y = ys * frequency / self.tc.scale
            noise = opensimplex.noise2array(scaled_x, scaled_y)
            result += noise * amplitude
            max_amplitude += amplitude
            amplitude *= self.tc.persistence
            frequency *= 2.0

        result /= max_amplitude
        return result

    def _apply_ns_gradient(self, raw: np.ndarray, h: int) -> np.ndarray:
        """Ajoute un léger gradient nord-sud (plus haut au nord = y=0)."""
        gradient = np.linspace(self.tc.ns_gradient_strength, -self.tc.ns_gradient_strength, h)
        raw += gradient[:, np.newaxis]
        return raw

    def _apply_central_flat(self, raw: np.ndarray, w: int, h: int) -> np.ndarray:
        """Aplatit la zone centrale (clubhouse) vers base_elevation."""
        cx = self.config.clubhouse_x
        cy = self.config.clubhouse_y
        radius = self.tc.central_flat_radius
        transition = self.tc.central_flat_transition

        # Valeur cible pour la zone centrale (0 dans l'espace brut = base_elevation)
        target = 0.0

        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)

        # Facteur de mélange : 1 au centre, 0 au-delà de radius + transition
        blend = np.clip((dist - radius) / transition, 0.0, 1.0)

        raw = raw * blend + target * (1 - blend)
        return raw

    @staticmethod
    def water_mask(heightmap: np.ndarray, water_level: float) -> np.ndarray:
        """Retourne un masque booleen : True = eau (elevation < water_level)."""
        return heightmap < water_level

    @staticmethod
    def sample_elevation(heightmap: np.ndarray | None, x: float, y: float,
                          default: float = 64.0) -> float:
        """Élévation du terrain à une position (clampée aux bords de la heightmap)."""
        if heightmap is None:
            return default
        ix = max(0, min(int(x), heightmap.shape[1] - 1))
        iy = max(0, min(int(y), heightmap.shape[0] - 1))
        return float(heightmap[iy, ix])

    def _normalize(self, raw: np.ndarray) -> np.ndarray:
        """Normalise dans [elevation_min, elevation_max]."""
        lo, hi = raw.min(), raw.max()
        if hi - lo < 1e-10:
            return np.full_like(raw, self.tc.base_elevation, dtype=np.float32)

        normalized = (raw - lo) / (hi - lo)
        elev_range = self.tc.elevation_max - self.tc.elevation_min
        heightmap = (normalized * elev_range + self.tc.elevation_min).astype(np.float32)
        return heightmap
