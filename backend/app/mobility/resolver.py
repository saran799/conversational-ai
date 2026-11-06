"""Stop resolver module (Worker 2 ownership).

Handles stop resolution with strict normalization, tiered matching:
1. Curated Alias lookup (data/curated/stop_aliases.csv)
2. Exact stop-name match (English / Tamil)
3. Partial stop-name match (English / Tamil)

Enforces:
- Ambiguity detection: If >1 distinct candidate stop exists, returns status: NEEDS_CLARIFICATION
  with a spoken question (e.g. "Did you mean Porur bus stand or Porur junction?").
- Never merges distinct stop IDs.
- Returns NO_MATCH if no candidate found and asks caller to repeat or name a nearby place.
- No geocoding fabrication.
"""
from dataclasses import dataclass, field
import csv
import logging
import os
import re
import unicodedata
from typing import Dict, List, Literal, Optional

from backend.app.mobility.models import Stop
from backend.app.mobility.repository import TransitRepository

logger = logging.getLogger(__name__)

ResolutionStatus = Literal["EXACT", "RESOLVED", "NEEDS_CLARIFICATION", "NO_MATCH", "ERROR"]


@dataclass
class ResolutionCandidate:
    stop_id: str
    stop_name: str
    stop_name_ta: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    mode: str = "bus"
    match_source: str = "alias"  # alias, exact, partial


@dataclass
class ResolutionResult:
    status: ResolutionStatus
    query: str
    candidates: List[ResolutionCandidate] = field(default_factory=list)
    selected_stop: Optional[ResolutionCandidate] = None
    clarification_question_en: Optional[str] = None
    clarification_question_ta: Optional[str] = None
    speech_prompt_en: Optional[str] = None
    speech_prompt_ta: Optional[str] = None


def normalize_query(text: str) -> str:
    """Normalize input: trim, lowercase, Unicode NFKC, collapse multiple whitespaces.
    Preserves Tamil and Unicode scripts intact.
    """
    if not text:
        return ""
    # Unicode normalize NFKC
    normalized = unicodedata.normalize("NFKC", text)
    # Lowercase
    normalized = normalized.lower()
    # Replace punctuation characters except spaces and alphanumeric/Tamil
    # Collapse multiple spaces
    normalized = re.sub(r"[\s\-_.,/]+", " ", normalized).strip()
    return normalized


class StopResolver:
    """Resolver for mapping colloquial spoken stop queries to canonical Stop entities."""

    def __init__(
        self,
        repository: TransitRepository,
        alias_file_path: Optional[str] = None,
    ):
        self.repo = repository
        self.alias_file_path = alias_file_path or os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data", "curated", "stop_aliases.csv"
        )
        self.aliases: Dict[str, List[str]] = {}  # normalized_alias -> list of stop_ids
        self._load_aliases()

    def _load_aliases(self) -> None:
        """Load curated alias mappings from CSV."""
        if not os.path.exists(self.alias_file_path):
            logger.warning("Alias file not found at %s. Proceeding with empty aliases.", self.alias_file_path)
            return

        try:
            with open(self.alias_file_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = row.get("status", "").strip().lower()
                    if status != "approved":
                        continue
                    alias_raw = row.get("alias", "")
                    stop_id = row.get("stop_id", "").strip()
                    if not alias_raw or not stop_id:
                        continue
                    norm_alias = normalize_query(alias_raw)
                    if norm_alias not in self.aliases:
                        self.aliases[norm_alias] = []
                    if stop_id not in self.aliases[norm_alias]:
                        self.aliases[norm_alias].append(stop_id)
            logger.info("Loaded %d unique alias phrases from %s", len(self.aliases), self.alias_file_path)
        except Exception as e:
            logger.error("Failed to load alias file: %s", e)

    def resolve(self, query: str, language: str = "en") -> ResolutionResult:
        """Resolve a stop name query following the strict order:
        (a) Curated alias table
        (b) Exact stop name match (EN / TA)
        (c) Partial stop name match (EN / TA)
        """
        norm_query = normalize_query(query)
        if not norm_query:
            return ResolutionResult(
                status="NO_MATCH",
                query=query,
                speech_prompt_en="Please provide a valid bus stop or station name.",
                speech_prompt_ta="தயவுசெய்து சரியான பேருந்து நிறுத்தம் அல்லது ரயில் நிலையத்தின் பெயரை கூறவும்.",
            )

        # 1. Check curated alias table
        matched_stop_ids = self.aliases.get(norm_query, [])
        if matched_stop_ids:
            candidates: List[ResolutionCandidate] = []
            for s_id in matched_stop_ids:
                stop_model = self.repo.get_stop_by_id(s_id)
                if stop_model:
                    candidates.append(
                        ResolutionCandidate(
                            stop_id=stop_model.stop_id,
                            stop_name=stop_model.stop_name,
                            stop_name_ta=stop_model.stop_name_ta,
                            latitude=stop_model.latitude,
                            longitude=stop_model.longitude,
                            mode=stop_model.mode,
                            match_source="alias",
                        )
                    )
            if candidates:
                return self._evaluate_candidates(norm_query, candidates, language)

        # 2. Check exact stop-name match from repository
        exact_stops = self._find_exact_matches(norm_query)
        if exact_stops:
            candidates = [
                ResolutionCandidate(
                    stop_id=s.stop_id,
                    stop_name=s.stop_name,
                    stop_name_ta=s.stop_name_ta,
                    latitude=s.latitude,
                    longitude=s.longitude,
                    mode=s.mode,
                    match_source="exact",
                )
                for s in exact_stops
            ]
            return self._evaluate_candidates(norm_query, candidates, language)

        # 3. Check partial stop-name match
        partial_stops = self.repo.search_stops(norm_query, limit=20)
        if partial_stops:
            candidates = [
                ResolutionCandidate(
                    stop_id=s.stop_id,
                    stop_name=s.stop_name,
                    stop_name_ta=s.stop_name_ta,
                    latitude=s.latitude,
                    longitude=s.longitude,
                    mode=s.mode,
                    match_source="partial",
                )
                for s in partial_stops
            ]
            return self._evaluate_candidates(norm_query, candidates, language)

        # 4. Nothing matches -> NO_MATCH
        return ResolutionResult(
            status="NO_MATCH",
            query=query,
            speech_prompt_en=f"I could not find any stop matching '{query}'. Could you repeat or name a nearby landmark?",
            speech_prompt_ta=f"'{query}' என்ற பெயரில் நிறுத்தம் எதுவும் கிடைக்கவில்லை. அருகிலுள்ள இடத்தை கூற முடியுமா?",
        )

    def _find_exact_matches(self, norm_query: str) -> List[Stop]:
        """Look for exact matches by searching candidates and comparing normalized names."""
        search_results = self.repo.search_stops(norm_query, limit=50)
        exacts: List[Stop] = []
        for s in search_results:
            name_en_norm = normalize_query(s.stop_name)
            name_ta_norm = normalize_query(s.stop_name_ta or "")
            if norm_query == name_en_norm or (name_ta_norm and norm_query == name_ta_norm):
                exacts.append(s)
        return exacts

    def _evaluate_candidates(
        self, query: str, candidates: List[ResolutionCandidate], language: str
    ) -> ResolutionResult:
        """Evaluate candidates: single unambiguous match vs multiple distinct candidates."""
        # De-duplicate by stop_id (preserving distinct stop IDs)
        unique_candidates: Dict[str, ResolutionCandidate] = {}
        for c in candidates:
            if c.stop_id not in unique_candidates:
                unique_candidates[c.stop_id] = c

        candidate_list = list(unique_candidates.values())

        if len(candidate_list) == 1:
            sel = candidate_list[0]
            status: ResolutionStatus = "EXACT" if sel.match_source in ("alias", "exact") else "RESOLVED"
            return ResolutionResult(
                status=status,
                query=query,
                candidates=candidate_list,
                selected_stop=sel,
            )

        # Multiple distinct candidates exist -> NEVER pick arbitrarily.
        # Formulate clarification question
        names_en = [c.stop_name for c in candidate_list[:3]]
        names_ta = [c.stop_name_ta or c.stop_name for c in candidate_list[:3]]

        q_en = f"Did you mean {' or '.join(names_en)}?"
        q_ta = f"நீங்கள் {' அல்லது '.join(names_ta)} என்பதைக் குறிப்பிடுகிறீர்களா?"

        return ResolutionResult(
            status="NEEDS_CLARIFICATION",
            query=query,
            candidates=candidate_list,
            selected_stop=None,
            clarification_question_en=q_en,
            clarification_question_ta=q_ta,
            speech_prompt_en=f"I found multiple locations for '{query}'. {q_en}",
            speech_prompt_ta=f"'{query}' என்பதற்கு பல நிறுத்தங்கள் உள்ளன. {q_ta}",
        )

