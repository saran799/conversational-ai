import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")
rows = conn.execute("SELECT DISTINCT service_category, stage, adult_fare_inr FROM bus_fares ORDER BY service_category, CAST(stage AS INTEGER)").fetchall()
for r in rows[:30]:
    print(r)

