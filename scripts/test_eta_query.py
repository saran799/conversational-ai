import datetime
import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")

def get_next_departure(stop_id: str, route_numbers: list[str], test_time: str = None):
    now = datetime.datetime.now()
    if test_time:
        current_time_str = test_time
        curr_seconds = int(test_time.split(":")[0]) * 3600 + int(test_time.split(":")[1]) * 60
    else:
        current_time_str = now.strftime("%H:%M")
        curr_seconds = now.hour * 3600 + now.minute * 60

    placeholders = ",".join("?" for _ in route_numbers)
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
    rows = conn.execute(q, [stop_id] + route_numbers + [current_time_str]).fetchall()
    if not rows:
        # Fallback: look for headway or all departures to find frequency
        q2 = f"""
        SELECT r.route_number, bs.departure_time
        FROM bus_schedules bs
        JOIN bus_trips bt ON bs.trip_id = bt.trip_id
        JOIN bus_routes r ON bt.route_id = r.route_id
        WHERE bs.stop_id = ? AND r.route_number IN ({placeholders})
        ORDER BY bs.departure_time ASC
        """
        all_rows = conn.execute(q2, [stop_id] + route_numbers).fetchall()
        return None, all_rows[:5], current_time_str, curr_seconds

    return rows[0], rows, current_time_str, curr_seconds

# Test for Porur with 88R and 49F at 09:10 AM
res, candidates, t_str, s_sec = get_next_departure("MTC:5738", ["88R", "49F"], test_time="09:10")
print("At 09:10 AM at Porur:", res)
h, m = map(int, res[1].split(":")[:2])
dep_sec = h * 3600 + m * 60
diff_mins = max(1, (dep_sec - s_sec) // 60)
print(f"Next bus: {res[0]} departing at {res[1]} (in ~{diff_mins} minutes)")

# Test for Avadi with S50, S45, 65E at 10:00 AM
res_a, cand_a, t_a, s_a = get_next_departure("MTC:10430", ["S50", "S45", "65E"], test_time="10:00")
print("\nAt 10:00 AM at Avadi:", res_a)
if res_a:
    h_a, m_a = map(int, res_a[1].split(":")[:2])
    dep_sec_a = h_a * 3600 + m_a * 60
    diff_a = max(1, (dep_sec_a - s_a) // 60)
    print(f"Next bus: {res_a[0]} departing at {res_a[1]} (in ~{diff_a} minutes)")
else:
    print("Candidates:", cand_a)
