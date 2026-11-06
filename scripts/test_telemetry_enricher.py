import datetime
import sqlite3
from typing import Dict, List, Optional

class TelemetryEnricher:
    def __init__(self, db_path: str = "data/build/chennai.sqlite"):
        self.db_path = db_path

    def get_arrival_estimate(
        self,
        stop_id: str,
        route_numbers: List[str],
        current_time_str: Optional[str] = None,
        stop_name: str = "the stop",
        stop_name_ta: Optional[str] = None,
    ) -> Dict:
        if not route_numbers or not stop_id:
            return {
                "available": False,
                "eta_minutes": None,
                "route_number": None,
                "text_en": "",
                "text_ta": "",
            }

        now = datetime.datetime.now()
        if not current_time_str:
            current_time_str = now.strftime("%H:%M")

        h_now, m_now = map(int, current_time_str.split(":")[:2])
        now_sec = h_now * 3600 + m_now * 60

        ta_stop = stop_name_ta or stop_name

        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            placeholders = ",".join("?" for _ in route_numbers)
            # Find next scheduled departure today
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
            rows = c.execute(q, [stop_id] + route_numbers + [current_time_str]).fetchall()

            if rows:
                best_route, best_time = rows[0]
                h_dep, m_dep = map(int, best_time.split(":")[:2])
                dep_sec = h_dep * 3600 + m_dep * 60
                diff_mins = max(1, (dep_sec - now_sec) // 60)

                # If departure is within 2 hours
                if diff_mins <= 120:
                    return {
                        "available": True,
                        "eta_minutes": diff_mins,
                        "route_number": best_route,
                        "scheduled_time": best_time,
                        "is_live": False,
                        "text_en": f"The next bus {best_route} is expected at {stop_name} in about {diff_mins} minutes (scheduled at {best_time}).",
                        "text_ta": f"அடுத்த பேருந்து {best_route} {ta_stop}க்கு சுமார் {diff_mins} நிமிடங்களில் ({best_time} மணிக்கு) வரும் என்று எதிர்பார்க்கப்படுகிறது.",
                    }

            # If no departure later today or diff > 120, calculate average headway
            q_headway = f"""
            SELECT bs.departure_time
            FROM bus_schedules bs
            JOIN bus_trips bt ON bs.trip_id = bt.trip_id
            JOIN bus_routes r ON bt.route_id = r.route_id
            WHERE bs.stop_id = ? AND r.route_number IN ({placeholders})
            ORDER BY bs.departure_time ASC
            """
            all_deps = [r[0] for r in c.execute(q_headway, [stop_id] + route_numbers).fetchall()]
            conn.close()

            if len(all_deps) >= 2:
                # Calculate median interval
                intervals = []
                for i in range(1, min(len(all_deps), 20)):
                    h1, m1 = map(int, all_deps[i-1].split(":")[:2])
                    h2, m2 = map(int, all_deps[i].split(":")[:2])
                    gap = (h2 * 60 + m2) - (h1 * 60 + m1)
                    if 3 <= gap <= 60:
                        intervals.append(gap)
                if intervals:
                    median_headway = sorted(intervals)[len(intervals) // 2]
                    est_wait = max(5, round(median_headway / 2.0))
                    r_display = route_numbers[0] if len(route_numbers) == 1 else f"{route_numbers[0]}"
                    return {
                        "available": True,
                        "eta_minutes": est_wait,
                        "route_number": r_display,
                        "scheduled_time": None,
                        "headway_minutes": median_headway,
                        "is_live": False,
                        "text_en": f"Bus {r_display} runs approximately every {median_headway} minutes from {stop_name}. Typical wait is about {est_wait} to {median_headway} minutes.",
                        "text_ta": f"பேருந்து {r_display} {ta_stop}வில் இருந்து சுமார் ஒவ்வொரு {median_headway} நிமிடங்களுக்கும் இயக்கப்படுகிறது. காத்திருப்பு நேரம் சுமார் {est_wait} முதல் {median_headway} நிமிடங்கள்.",
                    }

            # Generic fallback if no schedule rows for this stop/route
            return {
                "available": True,
                "eta_minutes": 10,
                "route_number": route_numbers[0],
                "scheduled_time": None,
                "is_live": False,
                "text_en": f"Bus {route_numbers[0]} frequency is typically every 10 to 15 minutes at {stop_name}.",
                "text_ta": f"பேருந்து {route_numbers[0]} வழக்கமாக {ta_stop}வில் 10 முதல் 15 நிமிட இடைவெளியில் கிடைக்கும்.",
            }

        except Exception as e:
            return {
                "available": False,
                "eta_minutes": None,
                "route_number": None,
                "text_en": "",
                "text_ta": "",
                "error": str(e)
            }

te = TelemetryEnricher()
print("Porur test:", te.get_arrival_estimate("MTC:5738", ["88R", "49F"], current_time_str="09:10", stop_name="Porur", stop_name_ta="போரூர்"))
print("\nAvadi test:", te.get_arrival_estimate("MTC:10430", ["S50", "65E"], current_time_str="10:00", stop_name="Avadi", stop_name_ta="ஆவடி"))
print("\nNight test:", te.get_arrival_estimate("MTC:5738", ["88R", "49F"], current_time_str="23:45", stop_name="Porur", stop_name_ta="போரூர்"))

