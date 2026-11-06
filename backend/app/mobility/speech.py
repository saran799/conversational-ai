"""Speech formatter module (Worker 2 ownership).

Generates natural spoken scripts in English and Tamil for Worker 1 TTS and call playback.
TTS-Friendly Rules:
1. Short sentences; at most the best option and 2 to 3 steps.
2. Spell out route numbers and symbols (e.g. 'S twenty-seven' or 'S 27').
3. No tables, URLs, markdown or abbreviations.
4. Always includes the plain caveat: 'This is from an older timetable and may have changed.'
5. Always includes fare and advisory status in one sentence each.
6. Offers follow-up: 'Would you like to hear the next route option?'
7. Uses centralized message catalogues (messages_en.json, messages_ta.json).
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from backend.app.mobility.engine import EngineJourneyOption, EngineJourneyResult

logger = logging.getLogger(__name__)


def spell_out_route(route_str: str, lang: str = "en") -> str:
    """Format route identifiers cleanly for TTS synthesizers."""
    if not route_str:
        return ""
    # E.g. 'S27' -> 'S 27'
    m = re.match(r"^([A-Za-z]+)(\d+.*)$", route_str.strip())
    if m:
        prefix, rest = m.groups()
        return f"{' '.join(list(prefix.upper()))} {rest}"
    return route_str


class SpeechFormatter:
    """Formats EngineJourneyResult into speech text for TTS synthesis."""

    def __init__(self, locale_dir: Optional[str] = None):
        self.locale_dir = locale_dir or os.path.dirname(__file__)
        self.msg_en: Dict[str, str] = self._load_json("messages_en.json")
        self.msg_ta: Dict[str, str] = self._load_json("messages_ta.json")

    def _load_json(self, filename: str) -> Dict[str, str]:
        path = os.path.join(self.locale_dir, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed loading %s: %s", filename, e)
        return {}

    def format_speech(
        self,
        journey_result: EngineJourneyResult,
        language: str = "en",
        fare_status: Optional[str] = "UNKNOWN",
        fare_amount: Optional[float] = None,
        advisories: Optional[List[str]] = None,
        arrival_estimate: Optional[Dict[str, Any]] = None,
        train_metro_alternative: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Produce spoken speech_text and follow-up question."""
        lang = "ta" if language.lower().startswith("ta") else "en"
        msgs = self.msg_ta if lang == "ta" else self.msg_en

        if journey_result.status == "NO_ROUTE" or not journey_result.options:
            return {
                "speech_text": msgs.get("no_route", "No route found."),
                "follow_up_question": None,
            }

        best = journey_result.options[0]
        sentences: List[str] = []

        origin_name = journey_result.origin_stop.stop_name_ta if (lang == "ta" and journey_result.origin_stop.stop_name_ta) else journey_result.origin_stop.stop_name
        dest_name = journey_result.destination_stop.stop_name_ta if (lang == "ta" and journey_result.destination_stop.stop_name_ta) else journey_result.destination_stop.stop_name

        # 1. Step-by-step route
        if best.transfers == 0 and len(best.legs) >= 1:
            route_spelled = spell_out_route(best.legs[0].route_number, lang)
            t_direct = msgs.get("direct_bus", "Take bus {route} from {origin} to {destination}.")
            sentences.append(t_direct.format(
                route=route_spelled,
                origin=origin_name,
                destination=dest_name,
                stops=best.total_stops,
            ))
        elif best.transfers >= 1 and len(best.legs) >= 2:
            r1 = spell_out_route(best.legs[0].route_number, lang)
            r2 = spell_out_route(best.legs[1].route_number, lang)
            t_stop = best.legs[0].alight_stop
            t_name = t_stop.stop_name_ta if (lang == "ta" and t_stop.stop_name_ta) else t_stop.stop_name
            t_trans = msgs.get("transfer_journey", "Take bus {route1} then bus {route2}.")
            sentences.append(t_trans.format(
                route1=r1,
                route2=r2,
                origin=origin_name,
                transfer_stop=t_name,
                destination=dest_name,
            ))

        # 2. Arrival estimate / Headway at boarding spot
        if arrival_estimate and arrival_estimate.get("available"):
            eta_str = arrival_estimate.get("text_ta") if lang == "ta" else arrival_estimate.get("text_en")
            if eta_str:
                sentences.append(eta_str)

        # 3. Fare statement
        if fare_status == "AVAILABLE" and fare_amount is not None:
            if lang == "ta":
                sentences.append(msgs.get("fare_known", "தோராயமான கட்டணம் {amount} ரூபாய்.").format(amount=int(fare_amount)))
            else:
                sentences.append(msgs.get("fare_known", "The estimated fare is {amount} rupees.").format(amount=int(fare_amount)))
        else:
            sentences.append(msgs.get("fare_unknown", "Fare is not confirmed."))

        # 4. Advisory statement
        if advisories and len(advisories) > 0:
            sentences.append(msgs.get("advisory_alert", "Notice: {summary}").format(summary=advisories[0]))
        else:
            sentences.append(msgs.get("advisory_none", "No traffic advisories reported in our records."))

        # 5. Mandatory caveat statement
        sentences.append(msgs.get("caveat_historical", "This is from an older timetable and may have changed."))

        # 6. Optional Train / Metro alternative notice
        if train_metro_alternative:
            alt_text = train_metro_alternative.get("text_ta") if lang == "ta" else train_metro_alternative.get("text_en")
            if alt_text:
                sentences.append(alt_text)

        # 7. Follow up question if alternatives exist
        follow_up = None
        if len(journey_result.options) > 1:
            follow_up = msgs.get("follow_up_next", "Would you like to hear the next route option?")

        full_speech = " ".join(sentences)

        return {
            "speech_text": full_speech,
            "follow_up_question": follow_up,
        }

