"""Telemetry and Live/Scheduled ETA Enrichment Module.

Provides real-time and scheduled arrival estimation for boarding stops in Chennai.
1. Primary: Queries GTFS stop departures from `bus_schedules` to calculate the next
   scheduled bus arrival time and minutes remaining from the boarding stop.
2. Headway Fallback: During off-peak or late hours, calculates route headway / frequency.
3. Live Telemetry Hook: Abstract provider interface ready to connect to external live GPS feeds
   (e.g., Chalo or CUMTA/MTC telemetry) without breaking existing pipelines.
4. Natural speech formatting in both English and Tamil.
"""
from abc import ABC, abstractmethod
import datetime
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def format_tamil_stop_dative(name: str) -> str:
    """Format Tamil stop name with dative suffix '-க்கு' / '-வுக்கு'."""
    if not name:
        return ""
    if name.endswith("ர்"):
        return name + "க்கு"  # போரூருக்கு
    elif name.endswith("ம்"):
        return name[:-1] + "த்திற்கு"  # தாம்பரத்திற்கு
    elif name.endswith("ி") or name.endswith("ை") or name.endswith("ீ"):
        return name + "க்கு"  # கிண்டிக்கு, பூந்தமல்லிக்கு
    elif name.endswith("டு"):
        return name[:-1] + "ட்டுக்கு"  # வண்டலூருக்கு
    return name + "க்கு"


def format_tamil_stop_locative(name: str) -> str:
    """Format Tamil stop name with locative suffix '-இல்' / '-ல்'."""
    if not name:
        return ""
    if name.endswith("ர்"):
        return name + "ில்"  # போரூரில்
    elif name.endswith("ம்"):
        return name[:-1] + "த்தில்"  # தாம்பரத்தில்
    elif name.endswith("ி") or name.endswith("ை"):
        return name + "யில்"  # கிண்டியில்
    return name + "ில்"


class BaseTelemetryProvider(ABC):
    """Abstract base for live or scheduled telemetry."""

    @abstractmethod
    def get_arrival_estimate(
        self,
        stop_id: str,
        route_numbers: List[str],
        current_time_str: Optional[str] = None,
        stop_name: str = "",
        stop_name_ta: Optional[str] = None,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def get_train_metro_alternative(
        self,
        origin_name: str,
        destination_name: str,
        current_time_str: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        pass


class ScheduledTelemetryProvider(BaseTelemetryProvider):
    """Calculates arrival times from SQLite bus_schedules table."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..", "data", "build", "chennai.sqlite"
        )

    def get_arrival_estimate(
        self,
        stop_id: str,
        route_numbers: List[str],
        current_time_str: Optional[str] = None,
        stop_name: str = "the boarding stop",
        stop_name_ta: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not route_numbers or not stop_id:
            return {
                "available": False,
                "eta_minutes": None,
                "route_number": None,
                "scheduled_time": None,
                "is_live": False,
                "text_en": "",
                "text_ta": "",
                "source": "empty_query",
            }

        now = datetime.datetime.now()
        if not current_time_str:
            current_time_str = now.strftime("%H:%M")

        try:
            h_now, m_now = map(int, current_time_str.split(":")[:2])
            now_sec = h_now * 3600 + m_now * 60
        except Exception:
            h_now, m_now = now.hour, now.minute
            now_sec = h_now * 3600 + m_now * 60
            current_time_str = now.strftime("%H:%M")

        ta_stop = stop_name_ta or stop_name
        ta_dative = format_tamil_stop_dative(ta_stop)
        ta_locative = format_tamil_stop_locative(ta_stop)

        if not os.path.exists(self.db_path):
            return {
                "available": False,
                "eta_minutes": None,
                "route_number": route_numbers[0],
                "scheduled_time": None,
                "is_live": False,
                "text_en": f"Bus {route_numbers[0]} operates regularly from {stop_name}.",
                "text_ta": f"பேருந்து {route_numbers[0]} {ta_locative} இருந்து சீராக இயக்கப்படுகிறது.",
                "source": "db_not_found",
            }

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            clean_routes = [r.strip() for r in route_numbers if r.strip()]
            placeholders = ",".join("?" for _ in clean_routes)

            # Query 1: Earliest scheduled departure today >= current time
            q = f"""
            SELECT r.route_number, bs.departure_time
            FROM bus_schedules bs
            JOIN bus_trips bt ON bs.trip_id = bt.trip_id
            JOIN bus_routes r ON bt.route_id = r.route_id
            WHERE bs.stop_id = ? AND r.route_number IN ({placeholders})
              AND bs.departure_time >= ?
            ORDER BY bs.departure_time ASC
            LIMIT 5
            """
            rows = c.execute(q, [stop_id] + clean_routes + [current_time_str]).fetchall()

            if rows:
                best_route, best_time = rows[0]
                h_dep, m_dep = map(int, best_time.split(":")[:2])
                dep_sec = h_dep * 3600 + m_dep * 60
                diff_mins = max(1, (dep_sec - now_sec) // 60)

                if diff_mins <= 120:
                    conn.close()
                    return {
                        "available": True,
                        "eta_minutes": diff_mins,
                        "route_number": best_route,
                        "scheduled_time": best_time,
                        "is_live": False,
                        "text_en": f"The next bus {best_route} is expected at {stop_name} in about {diff_mins} minutes (scheduled at {best_time}).",
                        "text_ta": f"அடுத்த பேருந்து {best_route} {ta_dative} சுமார் {diff_mins} நிமிடங்களில் ({best_time} மணிக்கு) வரும் என்று எதிர்பார்க்கப்படுகிறது.",
                        "source": "gtfs_schedule",
                    }

            # Query 2: Off-peak / late hours fallback: calculate typical interval / headway
            q_headway = f"""
            SELECT bs.departure_time
            FROM bus_schedules bs
            JOIN bus_trips bt ON bs.trip_id = bt.trip_id
            JOIN bus_routes r ON bt.route_id = r.route_id
            WHERE bs.stop_id = ? AND r.route_number IN ({placeholders})
            ORDER BY bs.departure_time ASC
            """
            all_deps = [r[0] for r in c.execute(q_headway, [stop_id] + clean_routes).fetchall()]
            conn.close()

            if len(all_deps) >= 2:
                intervals = []
                for i in range(1, min(len(all_deps), 30)):
                    h1, m1 = map(int, all_deps[i - 1].split(":")[:2])
                    h2, m2 = map(int, all_deps[i].split(":")[:2])
                    gap = (h2 * 60 + m2) - (h1 * 60 + m1)
                    if 3 <= gap <= 60:
                        intervals.append(gap)
                if intervals:
                    median_headway = sorted(intervals)[len(intervals) // 2]
                    est_wait = max(5, round(median_headway / 2.0))
                    r_display = clean_routes[0]
                    return {
                        "available": True,
                        "eta_minutes": est_wait,
                        "route_number": r_display,
                        "scheduled_time": None,
                        "headway_minutes": median_headway,
                        "is_live": False,
                        "text_en": f"Bus {r_display} runs approximately every {median_headway} minutes from {stop_name}. Typical wait is about {est_wait} to {median_headway} minutes.",
                        "text_ta": f"பேருந்து {r_display} {ta_locative} இருந்து சுமார் ஒவ்வொரு {median_headway} நிமிடங்களுக்கும் இயக்கப்படுகிறது. காத்திருப்பு நேரம் சுமார் {est_wait} முதல் {median_headway} நிமிடங்கள்.",
                        "source": "gtfs_headway",
                    }

            # Query 3: Default fallback
            r_display = clean_routes[0]
            return {
                "available": True,
                "eta_minutes": 10,
                "route_number": r_display,
                "scheduled_time": None,
                "headway_minutes": 15,
                "is_live": False,
                "text_en": f"Bus {r_display} operates approximately every 10 to 15 minutes at {stop_name}.",
                "text_ta": f"பேருந்து {r_display} வழக்கமாக {ta_locative} 10 முதல் 15 நிமிட இடைவெளியில் கிடைக்கும்.",
                "source": "default_frequency",
            }

        except Exception as e:
            logger.error("Error computing scheduled telemetry: %s", e)
            return {
                "available": False,
                "eta_minutes": None,
                "route_number": route_numbers[0] if route_numbers else None,
                "scheduled_time": None,
                "is_live": False,
                "text_en": "",
                "text_ta": "",
                "source": "error",
            }

    def get_train_metro_alternative(
        self,
        origin_name: str,
        destination_name: str,
        current_time_str: Optional[str] = None,
        origin_canonical_name: Optional[str] = None,
        destination_canonical_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Look up direct Metro or Suburban train alternative for this origin-destination corridor."""
        if not origin_name or not destination_name or not os.path.exists(self.db_path):
            return None

        now = datetime.datetime.now()
        if not current_time_str:
            current_time_str = now.strftime("%H:%M")

        try:
            h_now, m_now = map(int, current_time_str.split(":")[:2])
            now_sec = h_now * 3600 + m_now * 60
        except Exception:
            now_sec = now.hour * 3600 + now.minute * 60
            current_time_str = now.strftime("%H:%M")

        # Map common Tamil transliterations / aliases to canonical English keywords
        hub_trans = {
            "சென்ட்ரல்": "CENTRAL",
            "சென்னை": "CENTRAL",
            "கிண்டி": "GUINDY",
            "ஆவடி": "AVADI",
            "தாம்பரம்": "TAMBARAM",
            "எழும்பூர்": "EGMORE",
            "கோயம்பேடு": "KOYAMBEDU",
            "அடையாறு": "ADYAR",
            "வேளச்சேரி": "VELACHERY",
            "திருவான்மியூர்": "THIRUVANMIYUR",
            "மயிலாப்பூர்": "MYLAPORE",
            "சைதாப்பேட்டை": "SAIDAPET",
            "அம்பத்தூர்": "AMBATTUR",
        }

        orig_clean = hub_trans.get(origin_name.strip(), origin_name.strip().upper())
        dest_clean = hub_trans.get(destination_name.strip(), destination_name.strip().upper())

        # If canonical names provided from stop resolver (e.g. "Mgr Central Railway Station"), use them
        if origin_canonical_name:
            for k in ["CENTRAL", "GUINDY", "AVADI", "TAMBARAM", "EGMORE", "AIRPORT", "BEACH"]:
                if k in origin_canonical_name.upper():
                    orig_clean = k
                    break
        if destination_canonical_name:
            for k in ["CENTRAL", "GUINDY", "AVADI", "TAMBARAM", "EGMORE", "AIRPORT", "BEACH"]:
                if k in destination_canonical_name.upper():
                    dest_clean = k
                    break

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 1. Check direct Metro line
            q_metro = """
            SELECT mr.route_number, mr.route_name, s1.stop_id, s1.stop_name, s2.stop_id, s2.stop_name,
                   (CAST(rs2.stop_sequence AS INT) - CAST(rs1.stop_sequence AS INT)) as stops_count
            FROM metro_route_stops rs1
            JOIN metro_route_stops rs2 ON rs1.pattern_id = rs2.pattern_id AND CAST(rs1.stop_sequence AS INT) < CAST(rs2.stop_sequence AS INT)
            JOIN metro_routes mr ON rs1.route_id = mr.route_id
            JOIN metro_stations s1 ON rs1.stop_id = s1.stop_id
            JOIN metro_stations s2 ON rs2.stop_id = s2.stop_id
            WHERE s1.stop_name LIKE ? AND s2.stop_name LIKE ?
            LIMIT 1
            """
            row_metro = c.execute(q_metro, (f"%{orig_clean}%", f"%{dest_clean}%")).fetchone()
            if row_metro:
                m_route_num, m_route_name, s1_id, s1_name, s2_id, s2_name, stops_cnt = row_metro
                # Check next metro schedule
                q_ms = """
                SELECT departure_time FROM metro_schedules
                WHERE stop_id = ? AND departure_time >= ?
                ORDER BY departure_time ASC LIMIT 1
                """
                sched = c.execute(q_ms, (s1_id, current_time_str)).fetchone()
                eta_m = None
                sched_time = None
                if sched:
                    sched_time = sched[0]
                    h_m, m_m = map(int, sched_time.split(":")[:2])
                    diff = max(1, (h_m * 3600 + m_m * 60 - now_sec) // 60)
                    if diff <= 60:
                        eta_m = diff
                conn.close()

                # Clean display stop name
                disp_origin = orig_clean.title()
                disp_dest = dest_clean.title()
                time_info_en = f"Next metro is at {sched_time} (in ~{eta_m} mins)." if eta_m else "Metros run every 7 to 10 minutes."
                time_info_ta = f"அடுத்த மெட்ரோ {sched_time} மணிக்கு (சுமார் {eta_m} நிமிடங்களில்) உள்ளது." if eta_m else "மெட்ரோ ரயில்கள் 7 முதல் 10 நிமிட இடைவெளியில் இயக்கப்படுகின்றன."

                return {
                    "mode": "metro",
                    "route": m_route_name,
                    "stops_count": stops_cnt,
                    "eta_minutes": eta_m,
                    "scheduled_time": sched_time,
                    "text_en": f"Also, direct Metro is available from {disp_origin} to {disp_dest} ({stops_cnt} stops). {time_info_en}",
                    "text_ta": f"மேலும், {disp_origin} முதல் {disp_dest} வரை நேரடி மெட்ரோ ரயில் உள்ளது ({stops_cnt} நிறுத்தங்கள்). {time_info_ta}",
                }

            # 2. Check direct Suburban local train (EMU)
            # Handle Central synonyms: CENTRAL, MAS, MASS
            dest_pattern = f"%{dest_clean}%"
            dest_extra = "CENTRAL" in dest_clean or "MAS" in dest_clean
            q_sub = """
            SELECT sr.route_number, sr.route_name, s1.stop_id, s1.stop_name, s2.stop_id, s2.stop_name,
                   (CAST(rs2.stop_sequence AS INT) - CAST(rs1.stop_sequence AS INT)) as stops_count
            FROM suburban_route_stops rs1
            JOIN suburban_route_stops rs2 ON rs1.pattern_id = rs2.pattern_id AND CAST(rs1.stop_sequence AS INT) < CAST(rs2.stop_sequence AS INT)
            JOIN suburban_routes sr ON rs1.route_id = sr.route_id
            JOIN suburban_stations s1 ON rs1.stop_id = s1.stop_id
            JOIN suburban_stations s2 ON rs2.stop_id = s2.stop_id
            WHERE s1.stop_name LIKE ? AND (s2.stop_name LIKE ? OR (? AND (s2.stop_name LIKE '%MAS%' OR s2.stop_name LIKE '%CENTRAL%')))
            LIMIT 1
            """
            row_sub = c.execute(q_sub, (f"%{orig_clean}%", dest_pattern, dest_extra)).fetchone()
            if row_sub:
                s_route_num, s_route_name, s1_id, s1_name, s2_id, s2_name, stops_cnt = row_sub
                # Check next suburban schedule
                q_ss = """
                SELECT departure_time FROM suburban_schedules
                WHERE stop_id = ? AND departure_time >= ?
                ORDER BY departure_time ASC LIMIT 1
                """
                sched = c.execute(q_ss, (s1_id, current_time_str)).fetchone()
                eta_s = None
                sched_time = None
                if sched:
                    sched_time = sched[0]
                    h_s, m_s = map(int, sched_time.split(":")[:2])
                    diff = max(1, (h_s * 3600 + m_s * 60 - now_sec) // 60)
                    if diff <= 60:
                        eta_s = diff
                conn.close()

                disp_origin = orig_clean.title()
                disp_dest = dest_clean.title()
                time_info_en = f"Next train is at {sched_time} (in ~{eta_s} mins)." if eta_s else "Suburban trains run every 10 to 15 minutes."
                time_info_ta = f"அடுத்த புறநகர் ரயில் {sched_time} மணிக்கு (சுமார் {eta_s} நிமிடங்களில்) உள்ளது." if eta_s else "புறநகர் ரயில்கள் 10 முதல் 15 நிமிட இடைவெளியில் இயக்கப்படுகின்றன."

                return {
                    "mode": "suburban",
                    "route": f"Train {s_route_name}",
                    "stops_count": stops_cnt,
                    "eta_minutes": eta_s,
                    "scheduled_time": sched_time,
                    "text_en": f"Also, direct Suburban local train is available from {disp_origin} to {disp_dest} ({stops_cnt} stations). {time_info_en}",
                    "text_ta": f"மேலும், {disp_origin} முதல் {disp_dest} வரை நேரடி புறநகர் ரயில் உள்ளது ({stops_cnt} நிலையங்கள்). {time_info_ta}",
                }

            conn.close()
            return None
        except Exception as e:
            logger.error("Error looking up train/metro alternative: %s", e)
            return None


class LiveTelemetryProvider(BaseTelemetryProvider):
    """Live GPS / Telemetry provider with automatic fallback to scheduled provider.
    Can be configured with live URL or webhook if telemetry API credentials are provided.
    """

    def __init__(
        self,
        live_api_url: Optional[str] = None,
        fallback_provider: Optional[BaseTelemetryProvider] = None,
        db_path: Optional[str] = None,
    ):
        self.live_api_url = live_api_url or os.getenv("MTC_LIVE_TELEMETRY_URL")
        self.fallback = fallback_provider or ScheduledTelemetryProvider(db_path=db_path)

    def get_arrival_estimate(
        self,
        stop_id: str,
        route_numbers: List[str],
        current_time_str: Optional[str] = None,
        stop_name: str = "",
        stop_name_ta: Optional[str] = None,
    ) -> Dict[str, Any]:
        # If external live API URL is configured, query it with strict timeout
        if self.live_api_url:
            try:
                import urllib.request
                import json
                params = urllib.parse.urlencode({"stop_id": stop_id, "routes": ",".join(route_numbers)})
                url = f"{self.live_api_url}?{params}"
                req = urllib.request.Request(url, headers={"User-Agent": "ChennaiTransitMobility/1.0"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("available"):
                            return data
            except Exception as e:
                logger.warning("Live telemetry feed failed or timed out (%s). Falling back to scheduled timetable.", e)

        # Fallback to local high-precision schedule
        return self.fallback.get_arrival_estimate(
            stop_id=stop_id,
            route_numbers=route_numbers,
            current_time_str=current_time_str,
            stop_name=stop_name,
            stop_name_ta=stop_name_ta,
        )

    def get_train_metro_alternative(
        self,
        origin_name: str,
        destination_name: str,
        current_time_str: Optional[str] = None,
        origin_canonical_name: Optional[str] = None,
        destination_canonical_name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.fallback.get_train_metro_alternative(
            origin_name=origin_name,
            destination_name=destination_name,
            current_time_str=current_time_str,
            origin_canonical_name=origin_canonical_name,
            destination_canonical_name=destination_canonical_name,
        )


# Default Singleton
_global_telemetry = LiveTelemetryProvider()

def get_telemetry_enricher() -> BaseTelemetryProvider:
    return _global_telemetry

