"""Interactive Terminal AI Assistant for Chennai Transit.
Allows testing natural queries (English, Tamil, Tanglish) using your keyboard
or simulated speech input, connecting directly with chennai.sqlite.
"""
import json
import os
import re
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from backend.app.mobility.engine import JourneyEngine
from backend.app.mobility.enrich.advisory import AdvisoryEnricher
from backend.app.mobility.enrich.distance import DistanceEnricher
from backend.app.mobility.enrich.fare import FareEnricher
from backend.app.mobility.enrich.telemetry import get_telemetry_enricher
from backend.app.mobility.repository import SQLiteTransitRepository
from backend.app.mobility.resolver import StopResolver
from backend.app.mobility.speech import SpeechFormatter

_KNOWN_ALIASES_SET = None


def _load_known_aliases() -> set:
    global _KNOWN_ALIASES_SET
    if _KNOWN_ALIASES_SET is not None:
        return _KNOWN_ALIASES_SET
    _KNOWN_ALIASES_SET = set()
    alias_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "curated", "stop_aliases.csv")
    if os.path.exists(alias_path):
        import csv
        try:
            with open(alias_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("status") == "approved":
                        a = row.get("alias", "").strip().lower()
                        if a:
                            _KNOWN_ALIASES_SET.add(a)
        except Exception:
            pass
    return _KNOWN_ALIASES_SET


def _extract_known_stop_entities(clean: str) -> list:
    """Scan query tokens to locate known stop alias entities."""
    known = _load_known_aliases()
    clean_norm = re.sub(r"[?,.!;:()]+", " ", clean).strip()
    words = clean_norm.split()
    matched = []
    i = 0
    while i < len(words):
        if i + 2 < len(words):
            three = f"{words[i]} {words[i+1]} {words[i+2]}".lower()
            if three in known:
                matched.append(three)
                i += 3
                continue
        if i + 1 < len(words):
            two = f"{words[i]} {words[i+1]}".lower()
            if two in known:
                matched.append(two)
                i += 2
                continue
        one = words[i].lower()
        clean_w = re.sub(r"(?:யில்|யில|இல்|ில்|லிருந்து|இருந்து|லெருந்து|க்கு|கு)$", "", one)
        if clean_w.endswith("ர"):
            clean_w = clean_w[:-1] + "ர்"
        elif clean_w.endswith("ய"):
            clean_w = clean_w[:-1]
        if clean_w in known:
            matched.append(clean_w)
        i += 1
    return matched


def extract_origin_destination(text: str) -> dict:
    """Extract origin, destination, and language from natural spoken text.
    Handles English, Tamil, and Tanglish patterns.
    """
    clean = text.strip()
    lang = "en"
    if re.search(r"[\u0B80-\u0BFF]", clean):
        lang = "ta"

    origin = None
    destination = None

    # Pattern 1: Tamil natural speech variations
    # Example: "போரூரில் இருந்து கிண்டி போகணும்..." or "போரூரிலிருந்து கிண்டிக்கு..."
    # or "போரூர் டு கிண்டி போகணும்"
    if lang == "ta":
        # Check for 'டு' (to) pattern: "போரூர் டு கிண்டி"
        m_to = re.search(r"(\S+?)\s+டு\s+(\S+?)(?:\s+போகணும்|\s+போக|\s+bus|\s+பஸ்|$)", clean)
        if m_to:
            origin, destination = m_to.groups()
        else:
            tokens = clean.split()
            for idx, t in enumerate(tokens):
                # Check for origin indicator: word ending in 'இல்' / 'லிருந்து' / followed by 'இருந்து'
                if t == "இருந்து" and idx > 0:
                    raw_orig = tokens[idx - 1]
                    if raw_orig.endswith("த்தில்"):
                        origin = raw_orig[:-len("த்தில்")] + "ம்"
                    elif raw_orig.endswith("த்தில"):
                        origin = raw_orig[:-len("த்தில")] + "ம்"
                    else:
                        origin = re.sub(r"(?:யில்|யில|இல்|ில்|லிருந்து|இருந்து|லெருந்து|ல)$", "", raw_orig)
                        if origin.endswith("ர"):
                            origin = origin[:-1] + "ர்"
                        elif origin.endswith("ய"):
                            origin = origin[:-1]
                    # Next token(s) likely destination
                    if idx + 1 < len(tokens):
                        # Check if next tokens are multi-word e.g. "தி நகர்"
                        if tokens[idx + 1] in ("தி", "டி") and idx + 2 < len(tokens) and tokens[idx + 2].startswith("நகர்"):
                            destination = "தி நகர்"
                        else:
                            raw_dest = tokens[idx + 1]
                            destination = re.sub(r"(?:க்கு|கு|போகணும்|போக|செல்ல)$", "", raw_dest)
                    break
                elif "இருந்து" in t or "லிருந்து" in t:
                    origin = re.sub(r"(?:ிலிருந்|லிருந்|இருந்|லெருந்)து.*", "", t)
                    origin = re.sub(r"(?:யில்|யில|இல்|ில்)$", "", origin)
                    if origin.endswith("ர"):
                        origin = origin[:-1] + "ர்"
                    elif origin.endswith("ய"):
                        origin = origin[:-1]
                    if idx + 1 < len(tokens):
                        raw_dest = tokens[idx + 1]
                        destination = re.sub(r"(?:க்கு|கு|போகணும்|போக|செல்ல)$", "", raw_dest)
                    break

        # Fallback regex if tokens didn't catch both
        if not origin or not destination:
            m_ta = re.search(r"(\S+?)(?:இல்|ில்|ிலிருந்|லிருந்|இருந்)?(?:\s+இருந்து)?\s+(\S+?)(?:க்கு|கு|போகணும்|போக)", clean)
            if m_ta:
                origin, destination = m_ta.groups()
                origin = re.sub(r"(?:இல்|ில்|லிருந்து|இருந்து)$", "", origin)
                destination = re.sub(r"(?:க்கு|கு|போகணும்|போக)$", "", destination)

        # Clean Tamil stems (e.g., 'போரூர' -> 'போரூர்', 'ஆவடிய' -> 'ஆவடி')
        if origin:
            if origin.endswith("ர"):
                origin = origin[:-1] + "ர்"
            elif origin.endswith("ய"):
                origin = origin[:-1]
        if destination:
            if destination.endswith("ர"):
                destination = destination[:-1] + "ர்"
            elif destination.endswith("ய"):
                destination = destination[:-1]

    # Pattern 2: Tanglish "... lendhu ... poganum" or "... la irundhu ... poga"
    if not origin:
        m_tang = re.search(r"([A-Za-z]+)\s*(?:lendhu|lerundhu|la irundhu)\s*([A-Za-z]+)\s*(?:poganum|poga|ku|bus)", clean, re.IGNORECASE)
        if m_tang:
            origin, destination = m_tang.groups()

    # Pattern 3: English "from <origin> to <destination>"
    if not origin:
        m_en1 = re.search(r"from\s+([A-Za-z\s.]+?)\s+to\s+([A-Za-z\s.]+?)(?:\s+by|\s+bus|\s+train|\?|$)", clean, re.IGNORECASE)
        if m_en1:
            origin, destination = m_en1.groups()

    # Pattern 4: English "<origin> to <destination>"
    if not origin:
        m_en2 = re.search(r"([A-Za-z\s.]+?)\s+to\s+([A-Za-z\s.]+?)(?:\s+by|\s+bus|\s+train|\?|$)", clean, re.IGNORECASE)
        if m_en2:
            origin, destination = m_en2.groups()

    # Pattern 5: Entity-based fallback (detects known stops anywhere in query)
    if not origin or not destination:
        spots = _extract_known_stop_entities(clean)
        if len(spots) >= 2:
            origin = origin or spots[0]
            destination = destination or spots[1]
        elif len(spots) == 1 and not origin and not destination:
            if any(w in clean for w in ["போகணும்", "போனோம்", "போக", "செல்ல", "to ", "reach", "go to"]):
                destination = spots[0]
            else:
                origin = spots[0]

    # Fallback default cleanup
    if origin:
        origin = origin.strip(" ?,.")
    if destination:
        destination = destination.strip(" ?,.")

    return {
        "origin": origin,
        "destination": destination,
        "language": lang,
    }


def run_terminal_assistant():
    db_path = "data/build/chennai.sqlite"
    if not os.path.exists(db_path):
        print(f"Error: Database {db_path} not found. Please build it first.")
        return

    print("=" * 65)
    print("      CHENNAI MOBILITY AI - TERMINAL ASSISTANT       ")
    print("=" * 65)
    print("Loading SQLite transit database & stop aliases...")

    repo = SQLiteTransitRepository(db_path=db_path)
    resolver = StopResolver(repository=repo)
    engine = JourneyEngine(repository=repo)
    dist_enricher = DistanceEnricher()
    fare_enricher = FareEnricher()
    adv_enricher = AdvisoryEnricher()
    telemetry_enricher = get_telemetry_enricher()
    speech_formatter = SpeechFormatter()

    print("[Ready] Transit database connected successfully.\n")
    print("You can type or speak sample queries such as:")
    print("  1. 'How do I get from Porur to Guindy by bus?'")
    print("  2. 'Porur lendhu Guindy poganum. Enna bus edukkanum?'")
    print("  3. 'போரூரிலிருந்து கிண்டிக்கு போக என்ன பஸ் இருக்கு?'")
    print("  4. 'Tambaram to Guindy'")
    print("  5. 'Tambaram to T Nagar'")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            query = input("User Input > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting assistant.")
            break

        if not query:
            continue
        if query.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break

        # 1. Slot extraction
        extracted = extract_origin_destination(query)
        origin_raw = extracted["origin"]
        dest_raw = extracted["destination"]
        lang = extracted["language"]

        print(f"\n[AI Parser] Intent: JOURNEY_SEARCH | Language: {lang}")
        print(f"[Extracted Slots] Origin: '{origin_raw}' | Destination: '{dest_raw}'")

        if not origin_raw or not dest_raw:
            print("[Assistant] Could not clearly identify both origin and destination.")
            print("Please phrase like: 'from Porur to Guindy' or 'போரூரிலிருந்து கிண்டிக்கு'\n")
            continue

        # 2. Stop Resolution
        res_orig = resolver.resolve(origin_raw, language=lang)
        res_dest = resolver.resolve(dest_raw, language=lang)

        if res_orig.status == "NEEDS_CLARIFICATION":
            print(f"[Assistant Clarification] {res_orig.clarification_question_en}\n")
            continue
        if res_dest.status == "NEEDS_CLARIFICATION":
            print(f"[Assistant Clarification] {res_dest.clarification_question_en}\n")
            continue

        if not res_orig.selected_stop:
            print(f"[Assistant] Could not locate stop '{origin_raw}'.\n")
            continue
        if not res_dest.selected_stop:
            print(f"[Assistant] Could not locate stop '{dest_raw}'.\n")
            continue

        s_from = res_orig.selected_stop
        s_to = res_dest.selected_stop
        print(f"[Resolved Stops] Boarding: {s_from.stop_name} ({s_from.stop_id}) -> Alighting: {s_to.stop_name} ({s_to.stop_id})")

        # 3. Route Engine
        journey_result = engine.plan_journey(s_from.stop_id, s_to.stop_id)

        if journey_result.status != "OK" or not journey_result.options:
            print("[Assistant] No direct or 1-transfer route found in static feed.")
            print(f"Caveat: {journey_result.caveats}\n")
            continue

        # 4. Enrichment
        best = journey_result.options[0]
        first_leg = best.legs[0]
        last_leg = best.legs[-1]

        dist_res = dist_enricher.get_distance(
            s_from.latitude, s_from.longitude, s_to.latitude, s_to.longitude
        )
        fare_res = fare_enricher.get_fare(
            mode=first_leg.mode,
            from_stop_id=s_from.stop_id,
            to_stop_id=s_to.stop_id,
            distance_m=dist_res.straight_line_m,
        )
        matched_advs = adv_enricher.match_advisories(
            [l.board_stop.stop_name for l in best.legs] + [s_to.stop_name],
            [l.route_number for l in best.legs],
        )
        adv_texts = [a.message_en for a in matched_advs]

        # Telemetry arrival estimate at boarding stop
        first_routes = list({opt.legs[0].route_number for opt in journey_result.options if opt.legs and opt.legs[0].route_number})
        arrival_res = telemetry_enricher.get_arrival_estimate(
            stop_id=s_from.stop_id,
            route_numbers=first_routes,
            stop_name=s_from.stop_name,
            stop_name_ta=s_from.stop_name_ta,
        )

        # 5. Speech Generation
        speech = speech_formatter.format_speech(
            journey_result,
            language=lang,
            fare_status=fare_res.status,
            fare_amount=fare_res.amount_inr,
            advisories=adv_texts,
            arrival_estimate=arrival_res,
        )

        print("\n" + "-" * 55)
        print("          STRUCTURED ROUTE DETAILS               ")
        print("-" * 55)
        for i, opt in enumerate(journey_result.options, 1):
            route_str = " -> ".join([f"Bus {l.route_number} ({l.board_stop.stop_name} to {l.alight_stop.stop_name}, {l.stops_count} stops)" for l in opt.legs])
            print(f"Option {i} [{opt.ranking_basis}]: {route_str}")
        print(f"Estimated Distance: {round((dist_res.straight_line_m or 0) / 1000.0, 1)} km ({dist_res.method})")
        print(f"Fare Estimate     : {fare_res.status} ({fare_res.reason or '₹' + str(fare_res.amount_inr)})")
        print("-" * 55)
        print(f"\n>>> ASSISTANT SPOKEN OUTPUT ({lang.upper()}):\n")
        print(f"\"{speech['speech_text']}\"")
        if speech.get("follow_up_question"):
            print(f"Follow-up: \"{speech['follow_up_question']}\"")
        print("\n" + "=" * 65 + "\n")


if __name__ == "__main__":
    run_terminal_assistant()
