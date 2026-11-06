import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")

for t in ["bus_stops", "bus_routes", "bus_fares", "bus_frequency", "fare_rules", "stop_aliases"]:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
    print(f"Table {t} columns:", cols)

print("\nPoonamallee stops in bus_stops:")
for r in conn.execute("SELECT stop_id, stop_name FROM bus_stops WHERE stop_name LIKE '%Poonamalle%'").fetchall():
    print(r)

print("\nAvadi stops in bus_stops:")
for r in conn.execute("SELECT stop_id, stop_name FROM bus_stops WHERE stop_name LIKE '%Avadi%'").fetchall()[:10]:
    print(r)

print("\nSample bus_fares:")
for r in conn.execute("SELECT * FROM bus_fares LIMIT 5").fetchall():
    print(r)

print("\nSample bus_frequency:")
for r in conn.execute("SELECT * FROM bus_frequency LIMIT 5").fetchall():
    print(r)
