import sys
sys.path.insert(0, ".")
from backend.app.mobility.router import simulate_voice_query, SimulateQueryRequest

queries = [
    ("Porur to Guindy", "en"),
    ("போரூரில் இருந்து கிண்டிக்கு போகணும்", "ta"),
    ("Avadi to Poonamallee", "en"),
    ("ஆவடியில் இருந்து பூந்தமல்லிக்கு போகணும்", "ta"),
    ("from Avadi to poonamalle", "en"),
]

print("=" * 70)
print("             RUNNING END-TO-END FEATURE VERIFICATION")
print("=" * 70)

for q, lang in queries:
    req = SimulateQueryRequest(query=q, language=lang)
    res = simulate_voice_query(req)
    print(f"\nQUERY: '{q}' [{lang}]")
    print(f"STATUS: {res.get('status')}")
    print(f"SPEECH: {res.get('speech_text')}")
    arr = res.get("arrival_estimate")
    if arr:
        print(f"ARRIVAL ESTIMATE: ETA={arr.get('eta_minutes')}m | route={arr.get('route_number')} | text={arr.get('text_en')}")
    if res.get("options"):
        first_opt = res["options"][0]
        print(f"DISTANCE: {first_opt['distance']}")
        print(f"FARE: {first_opt['fare']}")
        routes = [l['route'] for l in first_opt['legs']]
        print(f"ROUTES: {routes}")
    print("-" * 50)

