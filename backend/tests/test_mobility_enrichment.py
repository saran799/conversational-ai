import os
from pathlib import Path
import pytest
from backend.app.mobility.enrich.distance import DistanceEnricher, haversine_km
from backend.app.mobility.enrich.fare import FareEnricher
from backend.app.mobility.enrich.advisory import AdvisoryEnricher, StoredAdvisory


def test_haversine_distance():
    # Porur (13.033, 80.158) to Guindy (13.008, 80.213) is roughly 6.6 km straight line
    dist = haversine_km(13.033, 80.158, 13.008, 80.213)
    assert 5.5 < dist < 8.0


def test_distance_fallback_haversine(tmp_path: Path):
    enricher = DistanceEnricher(cache_db_path=str(tmp_path / "test_dist.sqlite"))
    res = enricher.get_distance(13.033, 80.158, 13.008, 80.213)
    assert res.method == "straight-line lower bound"
    assert res.straight_line_m is not None
    assert 5500 < res.straight_line_m < 8000


def test_fare_bus_unknown():
    enricher = FareEnricher(metro_fares_file="nonexistent.csv")
    fare = enricher.get_fare(mode="bus", from_stop_id="MTC:5738", to_stop_id="MTC:1465")
    assert fare.status == "UNKNOWN"
    assert "stop-to-fare-stage mapping not available" in fare.reason


def test_fare_metro_curated(tmp_path: Path):
    f = tmp_path / "metro_fares.csv"
    f.write_text(
        "from_station_id,to_station_id,fare_inr,source_id,retrieved_on\n"
        "CMRL:M01,CMRL:M05,30.0,S_CMRL_OFFICIAL_FARE,2026-11-05\n",
        encoding="utf-8",
    )
    enricher = FareEnricher(metro_fares_file=str(f))
    fare = enricher.get_fare(mode="metro", from_stop_id="CMRL:M01", to_stop_id="CMRL:M05")
    assert fare.status == "AVAILABLE"
    assert fare.amount_inr == 30.0
    assert fare.data_status == "VERIFIED_CURATED"


def test_advisories_workflow(tmp_path: Path):
    db_file = str(tmp_path / "adv.sqlite")
    enricher = AdvisoryEnricher(db_path=db_file)

    # 1. Insert draft advisory
    draft_adv = StoredAdvisory(
        advisory_id="ADV_01",
        title="Flyover work at Porur",
        road_names="Mount Poonamallee Road",
        area="Porur",
        start_at="2026-11-01T00:00:00Z",
        end_at="2026-11-20T00:00:00Z",
        hours_text="24 hours",
        affected_modes="bus",
        effect_summary="Traffic restricted to single lane",
        source_name="Traffic Police",
        source_url="https://police.chennai.gov.in/notice1",
        retrieved_on="2026-11-05",
        review_status="draft",
        reviewed_by=None,
        expires_at="2026-11-20T00:00:00Z",
    )
    enricher.insert_advisory(draft_adv)

    # In draft state, should NOT match
    matches = enricher.match_advisories(stop_names=["Porur Bus Stand"], route_numbers=["54"])
    assert len(matches) == 0

    # 2. Approve advisory
    enricher.approve_advisory("ADV_01", reviewer="prakash")

    # Now approved, should match
    matches = enricher.match_advisories(stop_names=["Porur Bus Stand"], route_numbers=["54"])
    assert len(matches) == 1
    assert "Possible delay near Porur" in matches[0].message_en
    assert "Traffic restricted to single lane" in matches[0].message_en

    # 3. Expired advisory test
    expired_matches = enricher.match_advisories(
        stop_names=["Porur Bus Stand"], route_numbers=["54"], current_iso_time="2026-12-01T00:00:00Z"
    )
    assert len(expired_matches) == 0


def test_fare_bus_with_distance():
    enricher = FareEnricher(metro_fares_file="nonexistent.csv")
    fare = enricher.get_fare(mode="bus", from_stop_id="MTC:5738", to_stop_id="MTC:1465", distance_m=7000.0)
    assert fare.status == "AVAILABLE"
    assert fare.amount_inr == 8.0
    assert "S_MTC_FARES" in fare.source_id


def test_telemetry_arrival_estimate():
    from backend.app.mobility.enrich.telemetry import ScheduledTelemetryProvider
    telemetry = ScheduledTelemetryProvider(db_path="data/build/chennai.sqlite")
    res = telemetry.get_arrival_estimate("MTC:5738", ["88R", "49F"], current_time_str="09:10", stop_name="Porur", stop_name_ta="போரூர்")
    assert res["available"] is True
    assert res["route_number"] == "49F"
    assert res["eta_minutes"] == 7
    assert "09:17" in res["text_en"]


