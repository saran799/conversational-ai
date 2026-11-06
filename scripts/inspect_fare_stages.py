import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")
for cat in ['Ordinary Services', 'Deluxe Services', 'Express Services']:
    rows = conn.execute("SELECT stage, adult_fare_inr FROM bus_fares WHERE service_category=? ORDER BY CAST(stage AS INTEGER)", (cat,)).fetchall()
    print(f"\n{cat} (first 10 stages):", rows[:10])

