"""FastAPI Router for Chennai Mobility Backend (Worker 2 ownership).
Exposes:
- POST /api/mobility/routes/search
- GET /api/mobility/stops/search
- GET /api/mobility/diagnostics (dataset metadata, row counts, warnings)
"""
from typing import Any, Dict, List, Optional
import logging
import os
import uuid
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from backend.app.mobility.engine import JourneyEngine
from backend.app.mobility.enrich.advisory import AdvisoryEnricher
from backend.app.mobility.enrich.distance import DistanceEnricher
from backend.app.mobility.enrich.fare import FareEnricher
from backend.app.mobility.enrich.telemetry import BaseTelemetryProvider, get_telemetry_enricher
from backend.app.mobility.repository import SQLiteTransitRepository, TransitRepository
from backend.app.mobility.resolver import StopResolver
from backend.app.mobility.session import SessionManager
from backend.app.mobility.speech import SpeechFormatter
from backend.app.mobility.tools.simulate_call import extract_origin_destination

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mobility", tags=["mobility"])

# Singletons / dependencies
_repo: Optional[TransitRepository] = None
_resolver: Optional[StopResolver] = None
_engine: Optional[JourneyEngine] = None
_dist_enricher: Optional[DistanceEnricher] = None
_fare_enricher: Optional[FareEnricher] = None
_adv_enricher: Optional[AdvisoryEnricher] = None
_speech_formatter: Optional[SpeechFormatter] = None
_telemetry_enricher: Optional[BaseTelemetryProvider] = None
_session_mgr = SessionManager()


def get_repo() -> TransitRepository:
    global _repo
    if _repo is None:
        _repo = SQLiteTransitRepository()
    return _repo


def get_resolver(repo: TransitRepository = Depends(get_repo)) -> StopResolver:
    global _resolver
    if _resolver is None:
        _resolver = StopResolver(repository=repo)
    return _resolver


def get_engine(repo: TransitRepository = Depends(get_repo)) -> JourneyEngine:
    global _engine
    if _engine is None:
        _engine = JourneyEngine(repository=repo)
    return _engine


def get_dist_enricher() -> DistanceEnricher:
    global _dist_enricher
    if _dist_enricher is None:
        _dist_enricher = DistanceEnricher()
    return _dist_enricher


def get_fare_enricher() -> FareEnricher:
    global _fare_enricher
    if _fare_enricher is None:
        _fare_enricher = FareEnricher()
    return _fare_enricher


def get_adv_enricher() -> AdvisoryEnricher:
    global _adv_enricher
    if _adv_enricher is None:
        _adv_enricher = AdvisoryEnricher()
    return _adv_enricher


def get_speech_formatter() -> SpeechFormatter:
    global _speech_formatter
    if _speech_formatter is None:
        _speech_formatter = SpeechFormatter()
    return _speech_formatter


def get_telemetry() -> BaseTelemetryProvider:
    global _telemetry_enricher
    if _telemetry_enricher is None:
        _telemetry_enricher = get_telemetry_enricher()
    return _telemetry_enricher


class SimulateQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Natural language spoken query")
    language: str = Field(default="en", description="Optional language preference")


@router.get("/workbench", response_class=HTMLResponse)
def get_voice_workbench():
    """Serves the Terminal Voice Workbench HTML page."""
    html_path = os.path.join(os.path.dirname(__file__), "templates", "workbench.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Workbench template not found</h1>"


@router.post("/simulate")
def simulate_voice_query(
    req: SimulateQueryRequest,
    repo: TransitRepository = Depends(get_repo),
    resolver: StopResolver = Depends(get_resolver),
    engine: JourneyEngine = Depends(get_engine),
    dist_enricher: DistanceEnricher = Depends(get_dist_enricher),
    fare_enricher: FareEnricher = Depends(get_fare_enricher),
    adv_enricher: AdvisoryEnricher = Depends(get_adv_enricher),
    speech_formatter: SpeechFormatter = Depends(get_speech_formatter),
    telemetry: BaseTelemetryProvider = Depends(get_telemetry),
):
    """Processes natural language spoken query directly and delegates to search_routes."""
    # Ensure dependencies are resolved if invoked directly without FastAPI DI
    from fastapi.params import Depends as DependsClass
    repo = get_repo() if isinstance(repo, DependsClass) else repo
    resolver = get_resolver(repo) if isinstance(resolver, DependsClass) else resolver
    engine = get_engine(repo) if isinstance(engine, DependsClass) else engine
    dist_enricher = get_dist_enricher() if isinstance(dist_enricher, DependsClass) else dist_enricher
    fare_enricher = get_fare_enricher() if isinstance(fare_enricher, DependsClass) else fare_enricher
    adv_enricher = get_adv_enricher() if isinstance(adv_enricher, DependsClass) else adv_enricher
    speech_formatter = get_speech_formatter() if isinstance(speech_formatter, DependsClass) else speech_formatter
    telemetry = get_telemetry() if isinstance(telemetry, DependsClass) else telemetry

    extracted = extract_origin_destination(req.query)
    origin = extracted.get("origin")
    destination = extracted.get("destination")
    lang = extracted.get("language") or req.language

    logger.info("SIMULATE REQUEST received: query='%s', extracted_origin='%s', extracted_dest='%s', lang='%s'", req.query, origin, destination, lang)

    if not origin or not destination:
        logger.warning("SIMULATE: Missing slot(s) origin='%s', dest='%s' from query '%s'", origin, destination, req.query)
        if not origin and destination:
            prompt_en = f"Where are you starting from to travel to {destination}?"
            prompt_ta = f"{destination}க்கு செல்ல எந்த இடத்தில் இருந்து புறப்படுகிறீர்கள்?"
        elif origin and not destination:
            prompt_en = f"Where would you like to go from {origin}?"
            prompt_ta = f"{origin}வில் இருந்து எங்கு செல்ல வேண்டும்?"
        else:
            prompt_en = "Could not identify origin and destination. Please say: from Porur to Guindy."
            prompt_ta = "பேருந்து தொடங்கும் மற்றும் சேரும் இடத்தைக் கண்டுபிடிக்க முடியவில்லை. உதாரணமாக: போரூரிலிருந்து கிண்டிக்கு என்று கூறவும்."

        return {
            "status": "NEEDS_CLARIFICATION",
            "data_status": "unverified",
            "language": lang,
            "speech_text": prompt_ta if lang == "ta" else prompt_en,
            "follow_up_question": prompt_ta if lang == "ta" else prompt_en,
            "options": [],
            "advisories": [],
            "caveats": ["origin or destination missing from voice extraction"],
            "session_id": f"sess_{uuid.uuid4().hex[:12]}",
        }

    search_req = SearchRoutesRequest(
        origin=origin,
        destination=destination,
        language=lang,
    )
    return search_routes(
        req=search_req,
        repo=repo,
        resolver=resolver,
        engine=engine,
        dist_enricher=dist_enricher,
        fare_enricher=fare_enricher,
        adv_enricher=adv_enricher,
        speech_formatter=speech_formatter,
        telemetry=telemetry,
    )


class SearchRoutesRequest(BaseModel):
    origin: str = Field(..., min_length=2, description="Origin stop name or landmark")
    destination: str = Field(..., min_length=2, description="Destination stop name or landmark")
    departure_time: Optional[str] = Field(None, description="ISO departure time")
    language: str = Field(default="en", description="Language preference ('en' or 'ta')")
    session_id: Optional[str] = Field(None, description="Session ID for multi-turn clarification")
    max_transfers: int = Field(default=2, ge=0, le=3)


@router.post("/routes/search")
def search_routes(
    req: SearchRoutesRequest,
    repo: TransitRepository = Depends(get_repo),
    resolver: StopResolver = Depends(get_resolver),
    engine: JourneyEngine = Depends(get_engine),
    dist_enricher: DistanceEnricher = Depends(get_dist_enricher),
    fare_enricher: FareEnricher = Depends(get_fare_enricher),
    adv_enricher: AdvisoryEnricher = Depends(get_adv_enricher),
    speech_formatter: SpeechFormatter = Depends(get_speech_formatter),
    telemetry: BaseTelemetryProvider = Depends(get_telemetry),
):
    session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    sess = _session_mgr.get_or_create(session_id)

    # 1. Resolve origin stop
    orig_res = resolver.resolve(req.origin, language=req.language)
    if orig_res.status in ("NEEDS_CLARIFICATION", "NO_MATCH"):
        return {
            "status": orig_res.status,
            "data_status": "unverified",
            "language": req.language,
            "speech_text": orig_res.speech_prompt_ta if req.language == "ta" else orig_res.speech_prompt_en,
            "follow_up_question": orig_res.clarification_question_ta if req.language == "ta" else orig_res.clarification_question_en,
            "options": [],
            "advisories": [],
            "caveats": ["origin unresolved"],
            "session_id": session_id,
        }

    # 2. Resolve destination stop
    dest_res = resolver.resolve(req.destination, language=req.language)
    if dest_res.status in ("NEEDS_CLARIFICATION", "NO_MATCH"):
        return {
            "status": dest_res.status,
            "data_status": "unverified",
            "language": req.language,
            "speech_text": dest_res.speech_prompt_ta if req.language == "ta" else dest_res.speech_prompt_en,
            "follow_up_question": dest_res.clarification_question_ta if req.language == "ta" else dest_res.clarification_question_en,
            "options": [],
            "advisories": [],
            "caveats": ["destination unresolved"],
            "session_id": session_id,
        }

    origin_stop_id = orig_res.selected_stop.stop_id
    dest_stop_id = dest_res.selected_stop.stop_id

    # 3. Plan journey using JourneyEngine
    journey_result = engine.plan_journey(
        origin_stop_id=origin_stop_id,
        destination_stop_id=dest_stop_id,
        departure_time=req.departure_time,
        max_transfers=req.max_transfers,
    )

    if journey_result.status != "OK" or not journey_result.options:
        speech = speech_formatter.format_speech(journey_result, language=req.language)
        return {
            "status": "NO_ROUTE",
            "data_status": "unverified",
            "language": req.language,
            "speech_text": speech["speech_text"],
            "follow_up_question": None,
            "options": [],
            "advisories": [],
            "caveats": journey_result.caveats,
            "session_id": session_id,
        }

    # 4. Enrich best option
    best_opt = journey_result.options[0]
    first_leg = best_opt.legs[0]
    last_leg = best_opt.legs[-1]

    # Distance
    dist_res = dist_enricher.get_distance(
        first_leg.board_stop.latitude,
        first_leg.board_stop.longitude,
        last_leg.alight_stop.latitude,
        last_leg.alight_stop.longitude,
    )

    # Fare
    fare_res = fare_enricher.get_fare(
        mode=first_leg.mode,
        from_stop_id=first_leg.board_stop.stop_id,
        to_stop_id=last_leg.alight_stop.stop_id,
        distance_m=dist_res.straight_line_m,
    )

    # Advisories
    all_stop_names = [leg.board_stop.stop_name for leg in best_opt.legs] + [last_leg.alight_stop.stop_name]
    all_routes = [leg.route_number for leg in best_opt.legs]
    matched_advisories = adv_enricher.match_advisories(all_stop_names, all_routes)
    adv_strings = [
        (a.message_ta if req.language == "ta" else a.message_en) for a in matched_advisories
    ]

    # Telemetry / Arrival estimate at boarding stop
    first_routes = list({opt.legs[0].route_number for opt in journey_result.options if opt.legs and opt.legs[0].route_number})
    arrival_res = telemetry.get_arrival_estimate(
        stop_id=first_leg.board_stop.stop_id,
        route_numbers=first_routes,
        current_time_str=req.departure_time,
        stop_name=first_leg.board_stop.stop_name,
        stop_name_ta=first_leg.board_stop.stop_name_ta,
    )

    # Check for direct Train / Metro alternatives
    train_alt = telemetry.get_train_metro_alternative(
        origin_name=req.origin,
        destination_name=req.destination,
        current_time_str=req.departure_time,
        origin_canonical_name=orig_res.selected_stop.stop_name if orig_res.selected_stop else None,
        destination_canonical_name=dest_res.selected_stop.stop_name if dest_res.selected_stop else None,
    )

    # 5. Format speech
    speech_output = speech_formatter.format_speech(
        journey_result,
        language=req.language,
        fare_status=fare_res.status,
        fare_amount=fare_res.amount_inr,
        advisories=adv_strings,
        arrival_estimate=arrival_res,
        train_metro_alternative=train_alt,
    )

    # Transform options to response shape
    resp_options = []
    for opt in journey_result.options:
        legs_data = [
            {
                "mode": l.mode,
                "route": l.route_number,
                "from_stop": {"stop_id": l.board_stop.stop_id, "name": l.board_stop.stop_name},
                "to_stop": {"stop_id": l.alight_stop.stop_id, "name": l.alight_stop.stop_name},
                "stops_count": l.stops_count,
            }
            for l in opt.legs
        ]
        resp_options.append({
            "legs": legs_data,
            "transfers": opt.transfers,
            "ranking_basis": opt.ranking_basis,
            "fare": {"status": fare_res.status, "reason": fare_res.reason, "amount_inr": fare_res.amount_inr},
            "distance": {
                "value_km": round((dist_res.straight_line_m or 0) / 1000.0, 2) if dist_res.straight_line_m else None,
                "basis": dist_res.method,
            },
        })

    return {
        "status": "OK",
        "data_status": "unverified",
        "language": req.language,
        "speech_text": speech_output["speech_text"],
        "follow_up_question": speech_output["follow_up_question"],
        "options": resp_options,
        "advisories": [a.model_dump() for a in matched_advisories],
        "arrival_estimate": arrival_res,
        "train_metro_alternative": train_alt,
        "caveats": journey_result.caveats,
        "session_id": session_id,
    }


@router.get("/stops/search")
def search_stops(
    query: str = Query(..., min_length=2),
    limit: int = Query(default=10, ge=1, le=50),
    repo: TransitRepository = Depends(get_repo),
):
    """Exposes stop search endpoint."""
    stops = repo.search_stops(query, limit=limit)
    return [
        {
            "stop_id": s.stop_id,
            "stop_name": s.stop_name,
            "stop_name_tamil": s.stop_name_ta,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "modes": [s.mode],
        }
        for s in stops
    ]


@router.get("/diagnostics")
def get_diagnostics(repo: TransitRepository = Depends(get_repo)):
    """Admin-only diagnostics reporting dataset metadata, sources, and status."""
    return repo.get_diagnostics()
