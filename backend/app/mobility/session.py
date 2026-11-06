"""In-memory session manager for multi-turn mobility dialogs.
Stores pending clarification states, resolved origin/destination stops with 10-minute TTL.
Does not store audio, transcripts, or personal data.
"""
import time
from typing import Any, Dict, Optional


class MobilitySession:
    def __init__(self, session_id: str, ttl_seconds: int = 600):
        self.session_id = session_id
        self.ttl_seconds = ttl_seconds
        self.last_active = time.time()
        self.state: Dict[str, Any] = {}

    def is_expired(self) -> bool:
        return (time.time() - self.last_active) > self.ttl_seconds

    def touch(self):
        self.last_active = time.time()


class SessionManager:
    def __init__(self, default_ttl: int = 600):
        self.default_ttl = default_ttl
        self.sessions: Dict[str, MobilitySession] = {}

    def get_or_create(self, session_id: str) -> MobilitySession:
        self.cleanup_expired()
        if session_id not in self.sessions or self.sessions[session_id].is_expired():
            self.sessions[session_id] = MobilitySession(session_id, self.default_ttl)
        else:
            self.sessions[session_id].touch()
        return self.sessions[session_id]

    def cleanup_expired(self):
        expired = [sid for sid, sess in self.sessions.items() if sess.is_expired()]
        for sid in expired:
            del self.sessions[sid]

