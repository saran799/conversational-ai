import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")

print("--- bus_frequency sample ---")
for r in conn.execute("SELECT * FROM bus_frequency LIMIT 10").fetchall():
    print(r)

print("--- Count bus_frequency ---")
print(conn.execute("SELECT COUNT(*) FROM bus_frequency").fetchone()[0])

print("--- Count bus_schedules ---")
print(conn.execute("SELECT COUNT(*) FROM bus_schedules").fetchone()[0])

print("--- bus_schedules sample for 88R or 49F ---")
q = """
SELECT r.route_number, bs.stop_id, s.stop_name, bs.arrival_time, bs.departure_time
FROM bus_schedules bs
JOIN bus_trips bt ON bs.trip_id = bt.trip_id
JOIN bus_routes r ON bt.route_id = r.route_id
JOIN bus_stops s ON bs.stop_id = s.stop_id
WHERE r.route_number IN ('88R', '49F', '65K', '266')
LIMIT 15
"""
for r in conn.execute(q).fetchall():
    print(r)

