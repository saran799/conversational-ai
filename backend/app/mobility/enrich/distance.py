"""Distance enrichment module (Worker 2 ownership).

1. Fallback first: straight-line (haversine) distance between boarding and alighting stops.
   Labeled 'straight-line lower bound', not road distance.
2. Optional upgrade: OpenRouteService directions using ORS_API_KEY from environment.
   OpenStreetMap-based, no real-time traffic.
3. Cache every ORS result in a small SQLite table keyed by rounded coordinates.
   Handles HTTP 403 (quota exhausted) and 429 (rate limit) by falling back to haversine.
   Never retries in a tight loop.
4. Labeled 'approximate road distance (OpenStreetMap routing)'.
"""
import math
import os
import sqlite3
import time
from typing import Optional, Tuple
import logging

from backend.app.mobility.models import DistanceResult

logger = logging.getLogger(__name__)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points on the earth in kilometers."""
    radius_earth_km = 6371.0088

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return round(radius_earth_km * c, 2)


class DistanceEnricher:
    """Computes or enriches distance for journey legs."""

    def __init__(self, cache_db_path: Optional[str] = None):
        self.ors_api_key = os.getenv("ORS_API_KEY")
        self.cache_db_path = cache_db_path or "data/build/distance_cache.sqlite"
        self._init_cache()

    def _init_cache(self):
        try:
            os.makedirs(os.path.dirname(self.cache_db_path), exist_ok=True)
            with sqlite3.connect(self.cache_db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ors_cache (
                        coord_key TEXT PRIMARY KEY,
                        distance_km REAL,
                        duration_mins REAL,
                        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning("Could not initialize distance cache db: %s", e)

    def _coord_key(self, lat1: float, lon1: float, lat2: float, lon2: float) -> str:
        # Round to 3 decimal places (~110m precision)
        return f"{lat1:.3f},{lon1:.3f}->{lat2:.3f},{lon2:.3f}"

    def get_distance(
        self,
        lat1: Optional[float],
        lon1: Optional[float],
        lat2: Optional[float],
        lon2: Optional[float],
    ) -> DistanceResult:
        """Returns distance calculation with explicit basis and provenance."""
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return DistanceResult(
                straight_line_m=None,
                walking_distance_m=None,
                method="UNKNOWN",
                source_id="S_ENRICH_DIST",
                data_status="UNKNOWN",
            )

        # 1. Check ORS cache if API key exists
        coord_k = self._coord_key(lat1, lon1, lat2, lon2)
        cached_dist = self._get_cached_ors(coord_k)
        if cached_dist is not None:
            return DistanceResult(
                straight_line_m=int(cached_dist * 1000),
                walking_distance_m=int(cached_dist * 1000),
                method="approximate road distance (OpenStreetMap routing via ORS cache)",
                source_id="S_OPENROUTESERVICE",
                data_status="HISTORICAL_UNVERIFIED",
            )

        # 2. If ORS_API_KEY is configured, try ORS once (with graceful fallback on 403/429/error)
        if self.ors_api_key:
            ors_dist = self._query_ors(lat1, lon1, lat2, lon2, coord_k)
            if ors_dist is not None:
                return DistanceResult(
                    straight_line_m=int(ors_dist * 1000),
                    walking_distance_m=int(ors_dist * 1000),
                    method="approximate road distance (OpenStreetMap routing)",
                    source_id="S_OPENROUTESERVICE",
                    data_status="HISTORICAL_UNVERIFIED",
                )

        # 3. Fallback: Straight-line haversine distance
        h_dist_km = haversine_km(lat1, lon1, lat2, lon2)
        return DistanceResult(
            straight_line_m=int(h_dist_km * 1000),
            walking_distance_m=None,
            method="straight-line lower bound",
            source_id="S_CALCULATED_HAVERSINE",
            data_status="HISTORICAL_UNVERIFIED",
        )

    def _get_cached_ors(self, coord_key: str) -> Optional[float]:
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT distance_km FROM ors_cache WHERE coord_key = ?", (coord_key,))
                row = cur.fetchone()
                return float(row[0]) if row else None
        except Exception:
            return None

    def _query_ors(self, lat1: float, lon1: float, lat2: float, lon2: float, coord_key: str) -> Optional[float]:
        """Query ORS Directions API with immediate fallback on failure (no tight retry loops)."""
        import urllib.request
        import json

        url = "https://api.openrouteservice.org/v2/directions/driving-car"
        headers = {
            "Authorization": self.ors_api_key,
            "Content-Type": "application/json",
        }
        body = json.dumps({"coordinates": [[lon1, lat1], [lon2, lat2]]}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                routes = data.get("routes", [])
                if routes:
                    dist_km = routes[0]["summary"]["distance"] / 1000.0
                    self._save_cache(coord_key, dist_km)
                    return dist_km
        except Exception as e:
            logger.warning("ORS API query failed (%s); falling back to haversine straight-line.", e)
            return None
        return None

    def _save_cache(self, coord_key: str, dist_km: float):
        try:
            with sqlite3.connect(self.cache_db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR REPLACE INTO ors_cache (coord_key, distance_km) VALUES (?, ?)",
                    (coord_key, dist_km),
                )
                conn.commit()
        except Exception:
            pass

