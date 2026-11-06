import sqlite3

conn = sqlite3.connect("data/build/chennai.sqlite")

print("Checking Avadi stops in route_stops:")
q = """
SELECT rs.stop_id, s.stop_name, COUNT(DISTINCT rs.route_id) as route_cnt
FROM route_stops rs
JOIN bus_stops s ON rs.stop_id = s.stop_id
WHERE s.stop_name LIKE '%Avadi%'
GROUP BY rs.stop_id, s.stop_name
ORDER BY route_cnt DESC
LIMIT 10
"""
for r in conn.execute(q).fetchall():
    print(r)

print("\nChecking Poonamallee stops in route_stops:")
q2 = """
SELECT rs.stop_id, s.stop_name, COUNT(DISTINCT rs.route_id) as route_cnt
FROM route_stops rs
JOIN bus_stops s ON rs.stop_id = s.stop_id
WHERE s.stop_name LIKE '%Poonamalle%'
GROUP BY rs.stop_id, s.stop_name
ORDER BY route_cnt DESC
LIMIT 10
"""
for r in conn.execute(q2).fetchall():
    print(r)

print("\nChecking Direct Routes between Avadi and Poonamallee:")
q3 = """
SELECT DISTINCT r.route_number, r.route_name
FROM route_stops rs1
JOIN route_stops rs2 ON rs1.pattern_id = rs2.pattern_id AND rs1.stop_sequence < rs2.stop_sequence
JOIN bus_routes r ON rs1.route_id = r.route_id
JOIN bus_stops s1 ON rs1.stop_id = s1.stop_id
JOIN bus_stops s2 ON rs2.stop_id = s2.stop_id
WHERE (s1.stop_name LIKE '%Avadi%' AND s2.stop_name LIKE '%Poonamalle%')
"""
for r in conn.execute(q3).fetchall():
    print(r)

