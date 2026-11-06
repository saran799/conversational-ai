"""CLI tool to ingest Greater Chennai Traffic Police plain-text diversion notices.
Validates extraction with Pydantic, inserts as draft for human review.
CLI command to approve: python ingest_advisory.py approve <id>
"""
import argparse
import datetime
import os
import sys
from pydantic import BaseModel, Field

from backend.app.mobility.enrich.advisory import AdvisoryEnricher, StoredAdvisory


class AdvisoryExtractSchema(BaseModel):
    advisory_id: str
    title: str
    road_names: str
    area: str
    start_at: str
    end_at: str
    hours_text: str
    affected_modes: str = "bus,all"
    effect_summary: str
    source_name: str = "Greater Chennai Traffic Police"
    source_url: str
    review_status: str = "draft"
    reviewed_by: str = ""
    expires_at: str


def main():
    parser = argparse.ArgumentParser(description="Ingest or approve Chennai traffic advisories.")
    subparsers = parser.add_subparsers(dest="command")

    approve_parser = subparsers.add_parser("approve", help="Approve an advisory ID")
    approve_parser.add_argument("advisory_id", help="The ID of the advisory to approve")
    approve_parser.add_argument("--reviewer", default="prakash", help="Reviewer username")

    args = parser.parse_args()
    enricher = AdvisoryEnricher()

    if args.command == "approve":
        enricher.approve_advisory(args.advisory_id, args.reviewer)
        print(f"Advisory {args.advisory_id} approved by {args.reviewer}.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

