import sys
sys.path.insert(0, ".")
from backend.app.mobility.repository import SQLiteTransitRepository
from backend.app.mobility.engine import JourneyEngine

repo = SQLiteTransitRepository("data/build/chennai.sqlite")
engine = JourneyEngine(repo)

avadi_id = "MTC:10430"
poonamallee_id = "MTC:5821"

result = engine.plan_journey(origin_stop_id=avadi_id, destination_stop_id=poonamallee_id)
print("Journey plan status:", result.status)
print("Options count:", len(result.options))
for opt in result.options[:5]:
    legs_desc = [f"{leg.mode} {leg.route_number} ({leg.board_stop.stop_name} -> {leg.alight_stop.stop_name}, {leg.stops_count} stops)" for leg in opt.legs]
    print(f"Option {opt.option_id}: {opt.transfers} transfers, legs: {legs_desc}")
