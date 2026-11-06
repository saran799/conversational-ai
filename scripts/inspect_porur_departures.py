import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")

q = """
SELECT r.route_number, bs.departure_time
FROM bus_schedules bs
JOIN bus_trips bt ON bs.trip_id = bt.trip_id
JOIN bus_routes r ON bt.route_id = r.route_id
WHERE bs.stop_id = 'MTC:5738' AND r.route_number IN ('88R', '49F')
ORDER BY bs.departure_time
LIMIT 20
"""
rows = conn.execute(q).fetchall()
print(f"Scheduled departures at Porur (MTC:5738):")
for r in rows:
    print(r)

print("\nTotal departures at Porur:")
print(conn.execute("SELECT COUNT(*) FROM bus_schedules WHERE stop_id = 'MTC:5738'").fetchone()[0])

