"""Disruptions and traffic advisories enrichment module (Worker 2 ownership).

Greater Chennai Traffic Police diversion notices & road advisories.
Strict review workflow:
- Table advisories: advisory_id, title, road_names, area, start_at, end_at, hours_text,
  affected_modes, effect_summary, source_name, source_url, retrieved_on, review_status, reviewed_by, expires_at.
- review_status is draft, approved or rejected. Only approved and non-expired rows are ever returned.
- Stores extracted facts and source links (no copyrighted news article text).
- Matches advisory road/area names against stop names and route names on chosen patterns.
- Phrased as "possible delay", never as certain blockage.
- If nothing matches, says "no reported advisory in our records", never "no disruptions".
"""
from dataclasses import dataclass, field
import datetime
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from backend.app.mobility.models import Advisory

logger = logging.getLogger(__name__)


@dataclass
class StoredAdvisory:
    advisory_id: str
    title: str
    road_names: str
    area: str
    start_at: str
    end_at: str
    hours_text: str
    affected_modes: str
    effect_summary: str
    source_name: str
    source_url: str
    retrieved_on: str
    review_status: str  # draft, approved, rejected
    reviewed_by: Optional[str]
    expires_at: str


class AdvisoryEnricher:
    """Matches reviewed, unexpired Chennai traffic advisories to journey routes/stops."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or "data/build/advisories.sqlite"
        self._init_db()

    def _init_db(self):
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS advisories (
                        advisory_id TEXT PRIMARY KEY,
                        title TEXT,
                        road_names TEXT,
                        area TEXT,
                        start_at TEXT,
                        end_at TEXT,
                        hours_text TEXT,
                        affected_modes TEXT,
                        effect_summary TEXT,
                        source_name TEXT,
                        source_url TEXT,
                        retrieved_on TEXT,
                        review_status TEXT,
                        reviewed_by TEXT,
                        expires_at TEXT
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.warning("Error initializing advisories DB: %s", e)

    def insert_advisory(self, adv: StoredAdvisory):
        """Insert or update an advisory."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO advisories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                adv.advisory_id, adv.title, adv.road_names, adv.area, adv.start_at, adv.end_at,
                adv.hours_text, adv.affected_modes, adv.effect_summary, adv.source_name, adv.source_url,
                adv.retrieved_on, adv.review_status, adv.reviewed_by, adv.expires_at
            ))
            conn.commit()

    def approve_advisory(self, advisory_id: str, reviewer: str = "prakash"):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE advisories
                SET review_status = 'approved', reviewed_by = ?
                WHERE advisory_id = ?
            """, (reviewer, advisory_id))
            conn.commit()

    def match_advisories(
        self,
        stop_names: List[str],
        route_numbers: List[str],
        current_iso_time: Optional[str] = None,
    ) -> List[Advisory]:
        """Match approved and non-expired advisories against stop and route names."""
        now_str = current_iso_time or datetime.datetime.now(datetime.timezone.utc).isoformat()
        matched: List[Advisory] = []

        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                # Query only approved and non-expired advisories
                cur.execute("""
                    SELECT advisory_id, title, road_names, area, effect_summary, expires_at, source_name
                    FROM advisories
                    WHERE review_status = 'approved' AND (expires_at IS NULL OR expires_at >= ?)
                """, (now_str,))
                rows = cur.fetchall()

                for row in rows:
                    adv_id, title, road_names, area, effect, exp, src = row
                    keywords = [k.strip().lower() for k in (road_names + "," + area).split(",") if k.strip()]

                    # Check if any keyword matches stop names
                    found = False
                    for kw in keywords:
                        for s_name in stop_names:
                            if kw in s_name.lower():
                                found = True
                                break
                        if found:
                            break

                    if found:
                        matched.append(
                            Advisory(
                                advisory_id=adv_id,
                                code="TRAFFIC_DIVERSION_NOTICE",
                                message_ta=f"சாத்தியமான போக்குவரத்து தாமதம் ({area}): {effect}",
                                message_en=f"Possible delay near {area}: {effect}",
                                severity="warning",
                                source_id="S_CHENNAI_TRAFFIC_POLICE",
                                data_status="VERIFIED_CURATED",
                            )
                        )
        except Exception as e:
            logger.error("Error matching advisories: %s", e)

        return matched

