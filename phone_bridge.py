"""Complete Full-Duplex Phone Link AI Agent (192.168.137.1 <-> 192.168.137.171).

Commonized with Worker 2's Transit Laptop (http://192.168.137.171:8000/api/mobility/simulate):
1. Request JSON sent to 192.168.137.171:8000/api/mobility/simulate:
   {
     "query": "போரூரில் இருந்து கிண்டி போகணும் என்ன பஸ் எடுக்கணும்",
     "language": "ta"
   }
2. Response JSON received from 192.168.137.171:8000/api/mobility/simulate:
   {
     "status": "OK",
     "data_status": "unverified",
     "language": "ta",
     "speech_text": "Porur முதல் Guindy Bus Terminus வரை நேரடி பேருந்து 88R உள்ளது...",
     "follow_up_question": "அடுத்த வழித்தடத்தைப் பற்றி தெரிந்து கொள்ள விரும்புகிறீர்களா?",
     "options": [...],
     "advisories": [],
     "caveats": [...],
     "session_id": "sess_..."
   }
"""
import os
import subprocess
import sys

# Auto-relaunch with Python 3.11 if invoked from Python 3.14 / another interpreter
_PY311 = r"C:\Users\Nandheesaprasad\AppData\Local\Programs\Python\Python311\python.exe"
if os.path.exists(_PY311) and os.path.normcase(sys.executable) != os.path.normcase(_PY311):
    sys.exit(subprocess.call([_PY311, *sys.argv]))

import argparse
import asyncio
import io
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import edge_tts
import numpy as np
import pygame
import requests
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
from scipy.io.wavfile import write

# Windows consoles default to cp1252, which raises UnicodeEncodeError when we print Tamil
# transcripts/replies. Force UTF-8 so logging never crashes the agent mid-call.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# ================= NETWORK & AUDIO CONFIGURATION =================
TRANSIT_LAPTOP_IP = os.environ.get("TRANSIT_LAPTOP_IP", "192.168.137.171")
TRANSIT_SIMULATE_URL = f"http://{TRANSIT_LAPTOP_IP}:8000/api/mobility/simulate"
TRANSIT_SEARCH_FALLBACK_URL = f"http://{TRANSIT_LAPTOP_IP}:8000/api/mobility/routes/search"
TRANSIT_TURN_FALLBACK_URL = f"http://{TRANSIT_LAPTOP_IP}:8000/api/voice/turn"

STT_SAMPLE_RATE = 16000
SILENCE_DURATION = 1.8       # Seconds of silence after speech so natural pauses don't split origin/destination
MAX_UTTERANCE_SECONDS = 14.0 # Cap utterance length so noisy rooms never hang forever
POST_SPEECH_COOLDOWN = 2.4   # Cooldown after AI finishes speaking to absorb cellular + Bluetooth echo delay
# =================================================================

VOICES = {
    "ta": "ta-IN-PallaviNeural",  # Energetic, natural Tamil + English bilingual neural voice
    "en": "en-IN-NeerjaNeural",   # Warm Indian English female voice
}

# Phrases that only the AI says — if picked up from the phone speaker echo, ignore immediately!
_BOT_ECHO_PATTERNS = (
    "கண்டுபிடிக்க முடியவில்லை",
    "தொடங்கும் மற்றும் சேரும்",
    "நேரடி பேருந்து",
    "சுமார்",
    "நிறுத்தங்கள்",
    "கட்டணம் உறுதிப்படுத்தப்படவில்லை",
    "வழித்தடத்தைப் பற்றி",
    "விரும்புகிறீர்களா",
    "அட்டவணையில் இருந்து",
    "மொபிலிட்டி",
    "வரவேற்கிறோம்",
    "பயணம் இனிதாகட்டும்",
    "welcome to chennai mobility",
    "direct bus",
    "covering",
)

_AFFIRMATIVE_RE = re.compile(
    r"\b(yes|yeah|yep|sure|ok|okay|next|more|ama|aama|aamam|sollunga|sollu)\b"
    r"|ஆமா|ஆமாம்|சரி|சொல்லுங்க|சொல்லு|அடுத்த|வேணும்|வேண்டும்",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"\b(no|nope|nah|stop|enough|bye|thanks|thank you|vendam|vena|podhum)\b"
    r"|வேண்டாம்|வேணாம்|போதும்|நன்றி|வணக்கம் பை",
    re.IGNORECASE,
)
_GREETING_ONLY_RE = re.compile(
    r"^\s*(hello|hi|hey|vanakkam|namaskaram|ஹலோ|ஹாய்|வணக்கம்)\s*[.?!]*\s*$",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Returns 'ta' if Tamil characters or common Tanglish transit words are present, else 'en'."""
    for char in text:
        if "\u0b80" <= char <= "\u0bff":
            return "ta"
    lowered = text.lower()
    if any(tok in lowered.split() for tok in ("poganum", "irundhu", "enna", "epdi", "eppo", "sollunga", "vendam")):
        return "ta"
    return "en"


def _can_open_input_device(dev_index: int) -> Tuple[bool, int]:
    """Tests whether an input device can actually be opened without PortAudio -9999 errors."""
    try:
        dev_info = sd.query_devices(dev_index)
        native_sr = int(dev_info.get("default_samplerate") or STT_SAMPLE_RATE)
        for sr_candidate in (STT_SAMPLE_RATE, native_sr, 44100, 48000):
            try:
                with sd.InputStream(device=dev_index, channels=1, samplerate=sr_candidate):
                    return True, sr_candidate
            except Exception:
                continue
    except Exception:
        pass
    return False, STT_SAMPLE_RATE


def _can_open_output_device(dev_index: int) -> Tuple[bool, int]:
    """Tests whether an output device can actually be opened without PortAudio -9999 errors."""
    try:
        dev_info = sd.query_devices(dev_index)
        native_sr = int(dev_info.get("default_samplerate") or 24000)
        for sr_candidate in (24000, native_sr, 44100, 48000, 16000):
            try:
                with sd.OutputStream(device=dev_index, channels=1, samplerate=sr_candidate):
                    return True, sr_candidate
            except Exception:
                continue
    except Exception:
        pass
    return False, 24000


# Guard so Phone Link routing is applied at most once per process (and never re-hijacks
# the microphone on every TTS playback the way the old implementation did).
_PHONE_LINK_ROUTING_APPLIED = False


def _iter_active_capture_endpoints():
    """Yields (endpoint_guid, friendly_name_lower) for every ACTIVE capture (input) endpoint."""
    import winreg

    reg_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as key:
        for i in range(winreg.QueryInfoKey(key)[0]):
            sub = winreg.EnumKey(key, i)
            try:
                with winreg.OpenKey(key, sub) as sk:
                    state, _ = winreg.QueryValueEx(sk, "DeviceState")
                    if state != 1:  # 1 == DEVICE_STATE_ACTIVE
                        continue
                    name = ""
                    with winreg.OpenKey(sk, "Properties") as pk:
                        for j in range(winreg.QueryInfoKey(pk)[1]):
                            _, val, _ = winreg.EnumValue(pk, j)
                            if isinstance(val, str) and val.strip():
                                name += " " + val.lower()
                    yield sub, name
            except OSError:
                continue


def _find_active_capture_endpoint(*substrings: str) -> Optional[str]:
    """Returns the first active capture endpoint GUID whose friendly name contains any substring."""
    try:
        for guid, name in _iter_active_capture_endpoints():
            if any(s in name for s in substrings):
                return guid
    except Exception:
        pass
    return None


def ensure_phone_link_audio_routing() -> bool:
    """Routes audio for the Phone Link bridge WITHOUT hijacking the speech-to-text microphone.

    The old behaviour set 'Line 1 (Virtual Audio Cable)' as the Windows default input for ALL
    three roles (eConsole=0, eMultimedia=1, eCommunications=2). That broke recognition: every
    recognizer that reads the *default* mic (browsers, sounddevice defaults, etc.) ended up
    listening to the silent cable loopback and transcribing garbage like '3 5 3'.

    New behaviour:
      - Virtual Audio Cable is set ONLY as the Communications default (role 2). That is the device
        Microsoft Phone Link transmits to the remote caller, so the caller still hears the AI voice
        we write into the cable.
      - The real 'Microphone Array' is (re)asserted as the Console + Multimedia default (roles 0, 1),
        which is what speech-to-text uses by default — so recognition keeps hearing the real mic.
        This also self-heals a machine previously left with VAC forced onto every role.

    Applied at most once per process. Returns True once Communications routing to VAC succeeds.
    """
    global _PHONE_LINK_ROUTING_APPLIED
    if os.name != "nt" or _PHONE_LINK_ROUTING_APPLIED:
        return False
    try:
        import ctypes

        vac_guid = _find_active_capture_endpoint("virtual audio cable", "line 1")
        mic_guid = _find_active_capture_endpoint("microphone array")
        if not vac_guid and not mic_guid:
            return False

        ole32 = ctypes.oledll.ole32
        ole32.CoInitialize(None)

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

            def __init__(self, guid_str: str):
                ole32.CLSIDFromString(ctypes.c_wchar_p(guid_str), ctypes.byref(self))

        clsid = _GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")
        iid = _GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        p_policy = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(p_policy))
        if hr != 0 or not p_policy.value:
            return False

        vtable = ctypes.cast(
            ctypes.cast(p_policy, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        set_default_endpoint = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int
        )(vtable[13])

        # Keep the REAL microphone as Console (0) + Multimedia (1) default so STT hears the speaker.
        if mic_guid:
            mic_endpoint = f"{{0.0.1.00000000}}.{mic_guid}"
            for role in (0, 1):
                set_default_endpoint(p_policy, mic_endpoint, role)

        # Route ONLY the Communications role (2) to Virtual Audio Cable for Phone Link's call mic.
        applied_vac = False
        if vac_guid:
            vac_endpoint = f"{{0.0.1.00000000}}.{vac_guid}"
            set_default_endpoint(p_policy, vac_endpoint, 2)  # eCommunications
            applied_vac = True

        _PHONE_LINK_ROUTING_APPLIED = True
        return applied_vac
    except Exception:
        return False


# Backward-compatible alias — older call sites imported this name. It no longer makes VAC the
# *default* mic; it applies the safe comms-only routing above.
ensure_vac_is_windows_default_mic = ensure_phone_link_audio_routing


def find_safe_phone_audio_devices() -> Tuple[int, str, int, int, str, Optional[int]]:
    """Selects verified, live-signal input and dual output devices (Speakers + Virtual Cable/Phone).

    - Sets 'Line 1 (Virtual Audio Cable)' as Windows Default & Communications Input so Phone Link
      transmits Virtual Audio Cable audio to the remote phone caller.
    - Explicitly selects 'Microphone Array' (MME) for caller speech capture so we don't accidentally
      listen to our own Virtual Audio Cable.
    - Explicitly selects both 'Speakers (Realtek)' AND 'Line 1 (Virtual Audio Cable)' Output for dual playback.
    """
    ensure_phone_link_audio_routing()

    devices = sd.query_devices()
    default_out = sd.default.device[1] if sd.default.device[1] is not None else 5

    bt_in_idx = None
    mic_array_idx = None
    vac_out_idx = None
    speakers_out_idx = None

    for i, dev in enumerate(devices):
        name = dev["name"].lower()
        hostapi = int(dev.get("hostapi", 0))
        if hostapi not in (0, 1, 2):
            continue  # Skip raw WDM-KS kernel pins that throw -9999
        if dev["max_input_channels"] > 0:
            if ("oneplus" in name or "hands-free" in name) and bt_in_idx is None:
                ok, _ = _can_open_input_device(i)
                if ok:
                    bt_in_idx = i
            elif "microphone array" in name and hostapi == 0 and mic_array_idx is None:
                ok, _ = _can_open_input_device(i)
                if ok:
                    mic_array_idx = i
        if dev["max_output_channels"] > 0:
            if ("virtual audio cable" in name or "line 1" in name) and hostapi == 0 and vac_out_idx is None:
                ok, _ = _can_open_output_device(i)
                if ok:
                    vac_out_idx = i
            elif "speakers" in name and hostapi == 0 and speakers_out_idx is None:
                ok, _ = _can_open_output_device(i)
                if ok:
                    speakers_out_idx = i

    # Fallback scan across hostapis 0..2 if MME wasn't matched
    if mic_array_idx is None:
        for i, dev in enumerate(devices):
            name = dev["name"].lower()
            if int(dev.get("hostapi", 0)) in (0, 1, 2) and dev["max_input_channels"] > 0:
                if "microphone array" in name:
                    ok, _ = _can_open_input_device(i)
                    if ok:
                        mic_array_idx = i
                        break

    if vac_out_idx is None:
        for i, dev in enumerate(devices):
            name = dev["name"].lower()
            if int(dev.get("hostapi", 0)) in (0, 1, 2) and dev["max_output_channels"] > 0:
                if "virtual audio cable" in name or "line 1" in name:
                    ok, _ = _can_open_output_device(i)
                    if ok:
                        vac_out_idx = i
                        break

    # Choose Input: Bluetooth Hands-Free (if active) -> Explicit Microphone Array
    chosen_in = bt_in_idx if bt_in_idx is not None else (mic_array_idx if mic_array_idx is not None else 3)
    ok, chosen_in_sr = _can_open_input_device(chosen_in)
    if not ok:
        chosen_in, chosen_in_sr = 0, STT_SAMPLE_RATE
    chosen_in_name = devices[chosen_in]["name"]

    # Choose Primary Output (Speakers) + Secondary Output (Virtual Audio Cable for Phone Link call injection)
    chosen_out = speakers_out_idx if speakers_out_idx is not None else default_out
    chosen_out_name = devices[chosen_out]["name"]

    return chosen_in, chosen_in_name, chosen_in_sr, chosen_out, chosen_out_name, vac_out_idx


class ConversationSession:
    """Tracks multi-turn state with Worker 2's /api/mobility/simulate response options."""

    def __init__(self):
        self.session_id: str = f"sess_{int(time.time())}"
        self.last_options: List[Dict[str, Any]] = []
        self.option_cursor: int = 0
        self.last_language: str = "ta"
        self.awaiting_next_option_confirm: bool = False
        self.partial_utterance: str = ""
        self.last_ai_reply: str = ""

    def format_option_speech(self, opt: Dict[str, Any], language: str = "ta") -> str:
        """Formats an individual route option from Laptop 2's `options` array into natural speech."""
        legs = opt.get("legs") or []
        if not legs:
            return "மற்றொரு வழித்தடம் எதுவும் இல்லை." if language == "ta" else "No additional route options available."

        if len(legs) == 1:
            leg = legs[0]
            route = leg.get("route", "")
            mode = leg.get("mode", "bus")
            from_name = (leg.get("from_stop") or {}).get("name", "")
            to_name = (leg.get("to_stop") or {}).get("name", "")
            stops = leg.get("stops_count", 0)
            if language == "en":
                return (
                    f"Next option: Direct {mode} {route} is available from {from_name} to {to_name}, "
                    f"covering {stops} stops."
                )
            return (
                f"அடுத்த வழித்தடம்: {from_name} முதல் {to_name} வரை நேரடி பேருந்து {route} உள்ளது. "
                f"சுமார் {stops} நிறுத்தங்கள்."
            )

        parts_ta = []
        parts_en = []
        for leg in legs:
            route = leg.get("route", "")
            from_name = (leg.get("from_stop") or {}).get("name", "")
            to_name = (leg.get("to_stop") or {}).get("name", "")
            stops = leg.get("stops_count", 0)
            parts_ta.append(f"{from_name} முதல் {to_name} வரை பேருந்து {route} ({stops} நிறுத்தங்கள்)")
            parts_en.append(f"{route} from {from_name} to {to_name} ({stops} stops)")

        if language == "en":
            return "Next option with transfer: " + ", then ".join(parts_en) + "."
        return "அடுத்த மாற்று வழித்தடம்: " + ", பின்னர் ".join(parts_ta) + "."


def is_bot_echo(transcript: str, last_ai_reply: str = "") -> bool:
    """Returns True if the captured transcript is actually a delayed echo of the AI's own voice."""
    t_low = transcript.strip().lower()
    if not t_low:
        return True
    for pat in _BOT_ECHO_PATTERNS:
        if pat.lower() in t_low:
            return True
    if last_ai_reply:
        ai_words = set(re.findall(r"\w+", last_ai_reply.lower()))
        tr_words = re.findall(r"\w+", t_low)
        if len(tr_words) >= 2 and ai_words:
            overlap = sum(1 for w in tr_words if w in ai_words) / float(len(tr_words))
            if overlap >= 0.55:
                return True
    return False


def _post_simulate_candidate(candidate_query: str) -> Optional[Dict[str, Any]]:
    """Sends a single candidate query to Laptop 2 (/api/mobility/simulate) and returns JSON dict."""
    lang = detect_language(candidate_query)
    request_payload = {
        "query": candidate_query.strip(),
        "language": lang,
    }
    print(f"\n[📤 Request JSON -> {TRANSIT_SIMULATE_URL}]")
    print(json.dumps(request_payload, ensure_ascii=False, indent=2))
    try:
        resp = requests.post(
            TRANSIT_SIMULATE_URL,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=8.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"[📥 Response JSON <- Laptop 2 (HTTP 200, status={data.get('status')}, session={data.get('session_id')})]")
            return data
    except requests.exceptions.RequestException as exc:
        print(f"[⚠️ Network Notice] Could not reach {TRANSIT_SIMULATE_URL}: {exc}")
    return None


def _is_not_found_response(data: Optional[Dict[str, Any]]) -> bool:
    """Checks if Laptop 2 returned 'origin/destination not found'."""
    if not data:
        return True
    status = str(data.get("status") or "").upper()
    speech = str(data.get("speech_text") or "")
    options = data.get("options") or []
    if "கண்டுபிடிக்க முடியவில்லை" in speech or "could not find" in speech.lower():
        return True
    if status != "OK" and not options:
        return True
    return False


def query_transit_laptop(query_text: str, session: ConversationSession, alt_query_text: str = "") -> str:
    """Sends the exact commonized Request JSON to Laptop 2 (192.168.137.171:8000/api/mobility/simulate)
    and parses the exact Response JSON, with automatic fallback to alternate STT & multi-turn context."""
    lang = detect_language(query_text)
    session.last_language = lang
    cleaned = query_text.strip()
    alt_cleaned = alt_query_text.strip()

    # 1. Handle pure greeting instantly
    if _GREETING_ONLY_RE.match(cleaned) or (alt_cleaned and _GREETING_ONLY_RE.match(alt_cleaned)):
        if lang == "en":
            return "Hello! Welcome to Chennai Mobility AI. Where would you like to travel from and to today?"
        return "வணக்கம்! சென்னை மொபிலிட்டி AI-க்கு வரவேற்கிறோம். இன்னைக்கு நீங்க எங்கிருந்து எங்க போகணும்னு சொல்லுங்க?"

    # 2. Handle follow-up "Yes / ஆமா / அடுத்த வழித்தடம்" for cached options from previous turn
    if session.awaiting_next_option_confirm and len(cleaned.split()) <= 4:
        if _AFFIRMATIVE_RE.search(cleaned) or (alt_cleaned and _AFFIRMATIVE_RE.search(alt_cleaned)):
            if session.option_cursor < len(session.last_options):
                opt = session.last_options[session.option_cursor]
                session.option_cursor += 1
                speech = session.format_option_speech(opt, language=lang)
                if session.option_cursor < len(session.last_options):
                    follow = (
                        "Would you like to hear another option?"
                        if lang == "en"
                        else "இன்னொரு வழித்தடத்தைப் பற்றி தெரிந்து கொள்ள விரும்புகிறீர்களா?"
                    )
                    return f"{speech} {follow}"
                session.awaiting_next_option_confirm = False
                closing = (
                    "Would you like to search any other route?"
                    if lang == "en"
                    else "வேறு ஏதேனும் வழித்தடம் தேட வேண்டுமா?"
                )
                return f"{speech} {closing}"
            else:
                session.awaiting_next_option_confirm = False
                return (
                    "அனைத்து வழித்தடங்களையும் சொல்லிவிட்டேன். வேறு எங்காவது போக வேண்டுமா?"
                    if lang == "ta"
                    else "Those are all the available routes. Would you like to check another destination?"
                )

        if _NEGATIVE_RE.search(cleaned) or (alt_cleaned and _NEGATIVE_RE.search(alt_cleaned)):
            session.awaiting_next_option_confirm = False
            return (
                "மிக்க நன்றி! உங்கள் பயணம் இனிதாகட்டும். வணக்கம்!"
                if lang == "ta"
                else "Thank you for using Chennai Mobility AI! Have a safe journey!"
            )

    # 3. Build candidate queries in priority order:
    #    (a) Primary transcript (e.g. Tamil)
    #    (b) Combined with previous partial turn if caller spoke Origin then Destination across 2 breaths
    #    (c) Alternate transcript (e.g. English)
    candidates: List[str] = [cleaned]
    if session.partial_utterance and session.partial_utterance != cleaned:
        candidates.append(f"{session.partial_utterance} {cleaned}")
    if alt_cleaned and alt_cleaned.lower() != cleaned.lower():
        candidates.append(alt_cleaned)
        if session.partial_utterance:
            candidates.append(f"{session.partial_utterance} {alt_cleaned}")

    last_data: Optional[Dict[str, Any]] = None
    for candidate in candidates:
        data = _post_simulate_candidate(candidate)
        if data is None:
            continue
        last_data = data
        if not _is_not_found_response(data):
            # Found valid route! Reset partial utterance cache
            session.partial_utterance = ""
            if data.get("session_id"):
                session.session_id = str(data["session_id"])
            speech_text = str(data.get("speech_text") or "").strip()
            follow_up = str(data.get("follow_up_question") or "").strip()
            options = data.get("options") or []
            session.last_options = options
            session.option_cursor = 1 if len(options) > 1 else len(options)
            session.awaiting_next_option_confirm = bool(follow_up and len(options) > 1)
            if speech_text:
                return f"{speech_text} {follow_up}".strip() if follow_up else speech_text

    # If Laptop 2 returned "not found" on all candidates, remember this partial phrase (if it has words)
    # in case the caller just said the origin stop and is about to say the destination stop next!
    if last_data is not None:
        session.partial_utterance = cleaned
        speech_text = str(last_data.get("speech_text") or "").strip()
        if speech_text:
            return speech_text

    # 4. Fallback to /api/voice/turn if Laptop 2 is running the unified app
    try:
        turn_payload = {
            "call_id": session.session_id,
            "text_input": cleaned,
            "language_hint": lang,
        }
        resp = requests.post(TRANSIT_TURN_FALLBACK_URL, json=turn_payload, timeout=4.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("response_text"):
                return str(data["response_text"])
    except requests.exceptions.RequestException:
        pass

    # 5. Offline Demo Safety Fallback
    print("[ℹ️ Using local offline simulation fallback (Laptop 2 unreachable)]")
    return (
        f"வணக்கம்! நீங்கள் கேட்ட '{cleaned}' பயணத்திற்கான நேரடி பேருந்து விவரங்களை சரிபார்க்கிறேன். "
        "தயவுசெய்து புறப்படும் இடம் மற்றும் செல்லும் இடத்தை மீண்டும் கூறுங்கள்."
        if lang == "ta"
        else f"I heard '{cleaned}'. Could you please confirm your origin and destination stops?"
    )


def _prepare_stereo_44k_for_vac(mp3_bytes: bytes) -> np.ndarray:
    """Decodes MP3 bytes to 44.1kHz 2-channel stereo float32 normalized to 0.90 peak for Virtual Audio Cable."""
    samples, sr_rate = sf.read(io.BytesIO(mp3_bytes), dtype="float32")
    mono = samples[:, 0] if samples.ndim > 1 else samples.reshape(-1)
    if len(mono) == 0:
        return np.zeros((0, 2), dtype="float32")
    target_sr = 44100
    if sr_rate != target_sr:
        duration = len(mono) / float(sr_rate)
        target_len = max(1, int(duration * target_sr))
        x_old = np.linspace(0.0, duration, num=len(mono), endpoint=False)
        x_new = np.linspace(0.0, duration, num=target_len, endpoint=False)
        mono = np.interp(x_new, x_old, mono).astype(np.float32)
    peak = float(np.max(np.abs(mono)))
    if peak > 0.01:
        mono = (mono / peak * 0.90).astype(np.float32)
    return np.column_stack([mono, mono]).astype(np.float32)


def _write_to_vac_stream(stereo_44k: np.ndarray, vac_out_idx: int) -> None:
    """Streams stereo 44.1kHz audio directly into Virtual Audio Cable OutputStream for Phone Link."""
    try:
        if len(stereo_44k) == 0:
            return
        with sd.OutputStream(device=vac_out_idx, channels=2, samplerate=44100, dtype="float32") as vac_stream:
            vac_stream.write(stereo_44k)
            time.sleep(0.25)  # Allow MME output buffer to drain completely into Phone Link
    except Exception as exc:
        print(f"[⚠️ Virtual Audio Cable output warning]: {exc}")


async def speak_live(text: str, out_device_idx: Optional[int] = None, vac_out_idx: Optional[int] = None) -> None:
    """Synthesizes speech in memory and plays simultaneously to Speakers + Virtual Audio Cable (Phone Link)."""
    import threading

    lang = detect_language(text)
    voice_name = VOICES.get(lang, VOICES["ta"])
    rate = "+8%"
    pitch = "+5Hz" if lang == "ta" else "+0Hz"

    print(f"\n[🗣️ AI Speaking ({voice_name} -> Phone + Speakers)]: \"{text}\"")
    communicate = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)

    audio_buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.extend(chunk["data"])

    if not audio_buffer:
        return

    mp3_bytes = bytes(audio_buffer)

    # Start Virtual Audio Cable (Phone Call Microphone injection) thread simultaneously with Room Speakers
    vac_thread = None
    if vac_out_idx is not None:
        try:
            stereo_44k = _prepare_stereo_44k_for_vac(mp3_bytes)
            vac_thread = threading.Thread(
                target=_write_to_vac_stream,
                args=(stereo_44k, vac_out_idx),
                daemon=True,
            )
            vac_thread.start()
        except Exception as exc:
            print(f"[⚠️ VAC prep warning]: {exc}")

    # Play on primary room speakers via pygame mixer
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(io.BytesIO(mp3_bytes))
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(15)
        pygame.mixer.music.unload()
    except Exception:
        # Fallback direct sounddevice playback to room speakers
        samples, sr_rate = sf.read(io.BytesIO(mp3_bytes), dtype="float32")
        sd.play(samples, samplerate=sr_rate, device=out_device_idx, blocking=True)

    if vac_thread is not None:
        vac_thread.join(timeout=5.0)

    print("[✅ Finished speaking to Phone + Speakers]\n")


def resample_to_16k(audio_np: np.ndarray, orig_sr: int) -> np.ndarray:
    """Linearly resamples captured audio to 16000 Hz mono for STT."""
    flat = audio_np.reshape(-1)
    if orig_sr == STT_SAMPLE_RATE or len(flat) == 0:
        return flat
    duration = len(flat) / float(orig_sr)
    target_len = int(duration * STT_SAMPLE_RATE)
    if target_len <= 0:
        return flat
    x_old = np.linspace(0.0, duration, num=len(flat), endpoint=False)
    x_new = np.linspace(0.0, duration, num=target_len, endpoint=False)
    return np.interp(x_new, x_old, flat).astype(np.float32)


def find_vac_capture_input() -> Optional[Tuple[int, int]]:
    """Finds the Virtual Audio Cable RECORDING endpoint — the device Microsoft Phone Link's
    call *output* must be routed into so the bridge can hear the remote caller.

    Prefers MME (hostapi 0) then WASAPI/DirectSound for PortAudio reliability. Returns
    (device_index, samplerate) or None if no openable cable recording endpoint exists.
    """
    devices = sd.query_devices()
    for pref_hostapi in (0, 2, 1):  # MME, WASAPI, DirectSound
        for i, dev in enumerate(devices):
            name = dev["name"].lower()
            is_cable = ("virtual audio cable" in name) or ("line 1" in name)
            if is_cable and dev["max_input_channels"] > 0 and int(dev.get("hostapi", 0)) == pref_hostapi:
                ok, sr = _can_open_input_device(i)
                if ok:
                    return i, sr
    return None


def main():
    parser = argparse.ArgumentParser(description="Bi-Directional Phone Link AI Agent")
    parser.add_argument(
        "--simulate",
        "-s",
        type=str,
        help="Test a single query immediately (e.g. 'போரூரில் இருந்து கிண்டி போகணும் என்ன பஸ் எடுக்கணும்')",
    )
    parser.add_argument("--in-device", type=int, default=None, help="Override input audio device index")
    parser.add_argument("--out-device", type=int, default=None, help="Override output audio device index")
    parser.add_argument(
        "--phonelink",
        action="store_true",
        help="Microsoft Phone Link mode: capture the remote caller from the Virtual Audio Cable "
        "recording endpoint (set Phone Link's OUTPUT/speaker device to 'Line 1 (Virtual Audio Cable)'). "
        "The AI reply plays on the room speakers only (it is NOT injected into the same cable, which "
        "would feed back into recognition).",
    )
    args = parser.parse_args()

    session = ConversationSession()
    in_idx, in_name, in_sr, out_idx, out_name, vac_out_idx = find_safe_phone_audio_devices()

    if args.phonelink and args.in_device is None:
        vac_cap = find_vac_capture_input()
        if vac_cap is not None:
            in_idx, in_sr = vac_cap
            in_name = sd.query_devices(in_idx)["name"]
            # Capturing the cable means we must NOT also write the AI voice into that same cable,
            # or the reply would loop straight back into the recognizer.
            vac_out_idx = None
            print(f"[📞 Phone Link mode] Capturing caller from cable input [{in_idx}] {in_name}")
            print("     -> In Phone Link, set the call OUTPUT/speaker device to 'Line 1 (Virtual Audio Cable)'.")
        else:
            print("[⚠️ --phonelink] No openable Virtual Audio Cable recording endpoint found; "
                  "falling back to the auto-selected microphone.")

    if args.in_device is not None:
        in_idx = args.in_device
        in_name = sd.query_devices(in_idx)["name"]
        ok, detected_sr = _can_open_input_device(in_idx)
        if ok:
            in_sr = detected_sr
    if args.out_device is not None:
        out_idx = args.out_device
        out_name = sd.query_devices(out_idx)["name"]

    if args.simulate:
        reply_text = query_transit_laptop(args.simulate, session)
        asyncio.run(speak_live(reply_text, out_device_idx=out_idx, vac_out_idx=vac_out_idx))
        return

    print("=" * 72)
    print("   📞 CHENNAI MOBILITY AI — LIVE PHONE LINK AGENT (FULL-DUPLEX)   ")
    print("=" * 72)
    print(f"👂 Input Device (Caller)  : [{in_idx}] {in_name} ({in_sr} Hz)")
    print(f"🗣️ Output Device (Room)   : [{out_idx}] {out_name}")
    if vac_out_idx is not None:
        print(f"📲 Output Device (Cable)  : [{vac_out_idx}] {sd.query_devices(vac_out_idx)['name']}")
    print(f"🧠 Transit Brain Endpoint : {TRANSIT_SIMULATE_URL}")
    print("=" * 72)

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True

    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    # Calibrate ambient noise floor for 0.8s so room hum never false-triggers
    print("[🔧 Calibrating background noise level for 0.8s...]")
    ambient_rms = 0.0080
    try:
        calib_frames = int(0.8 * in_sr)
        rec = sd.rec(calib_frames, samplerate=in_sr, channels=1, dtype="float32", device=in_idx)
        sd.wait()
        measured = float(np.sqrt(np.mean(np.square(rec))))
        ambient_rms = max(0.0065, min(0.030, measured * 3.0))
    except Exception:
        ambient_rms = 0.0080
    print(f"[✅ Noise threshold calibrated: {ambient_rms:.4f}]")
    print("\n🎙️ Ready! Speak into the phone / mic (Press Ctrl+C to stop)...\n")

    # Pre-roll buffer (~0.5s) ensures the first word (Origin bus stop!) is NEVER cut off
    pre_roll: deque = deque(maxlen=40)
    audio_frames: List[np.ndarray] = []
    is_caller_speaking = False
    is_ai_speaking = False
    silence_start: Optional[float] = None
    utterance_start: Optional[float] = None
    cooldown_until: float = 0.0

    def audio_callback(indata, frames, time_info, status):
        nonlocal is_caller_speaking, silence_start, utterance_start
        # ECHO PREVENTION: Ignore mic input while AI is speaking or in cellular echo cooldown
        if is_ai_speaking or time.time() < cooldown_until:
            pre_roll.clear()
            return

        rms = float(np.sqrt(np.mean(np.square(indata))))
        now = time.time()

        if rms > ambient_rms:
            if not is_caller_speaking:
                print("\n[🎙️ Caller speaking...]", end="", flush=True)
                is_caller_speaking = True
                utterance_start = now
                # Prepend the 0.5s pre-roll so the first syllable of the Origin stop is preserved
                audio_frames.extend(pre_roll)
                pre_roll.clear()
            silence_start = None
            audio_frames.append(indata.copy())
            if utterance_start and (now - utterance_start) >= MAX_UTTERANCE_SECONDS:
                is_caller_speaking = False
        elif is_caller_speaking:
            audio_frames.append(indata.copy())
            if silence_start is None:
                silence_start = now
            elif (now - silence_start) >= SILENCE_DURATION:
                is_caller_speaking = False
        else:
            pre_roll.append(indata.copy())

    def _rec_lang(audio_data_obj, lang_code: str) -> str:
        try:
            return recognizer.recognize_google(audio_data_obj, language=lang_code).strip()
        except Exception:
            return ""

    with sd.InputStream(device=in_idx, channels=1, samplerate=in_sr, dtype="float32", callback=audio_callback):
        while True:
            time.sleep(0.08)
            min_frames_needed = max(6, int((in_sr * 0.65) / 512))
            if not is_caller_speaking and len(audio_frames) >= min_frames_needed:
                print(" [Transcribing...]")
                captured = np.concatenate(audio_frames, axis=0)
                audio_frames.clear()
                pre_roll.clear()
                utterance_start = None
                silence_start = None

                # Normalize & Resample to 16kHz PCM WAV in memory
                pcm_16k = resample_to_16k(captured, in_sr)
                peak = float(np.max(np.abs(pcm_16k))) if len(pcm_16k) else 0.0
                if peak > 0.01:
                    pcm_16k = pcm_16k / peak * 0.85
                wav_io = io.BytesIO()
                write(wav_io, STT_SAMPLE_RATE, np.clip(pcm_16k * 32767.0, -32768, 32767).astype(np.int16))
                wav_io.seek(0)

                try:
                    with sr.AudioFile(wav_io) as source:
                        audio_data = recognizer.record(source)

                    # Recognize BOTH Tamil (ta-IN) and Indian English (en-IN) in parallel
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        fut_ta = pool.submit(_rec_lang, audio_data, "ta-IN")
                        fut_en = pool.submit(_rec_lang, audio_data, "en-IN")
                        ta_text = fut_ta.result()
                        en_text = fut_en.result()

                    transcript = ta_text or en_text
                    alt_transcript = en_text if ta_text else ""

                    if transcript:
                        # Check if this is delayed cellular/speaker echo of the AI's own voice
                        if is_bot_echo(transcript, session.last_ai_reply) or (
                            alt_transcript and is_bot_echo(alt_transcript, session.last_ai_reply)
                        ):
                            print(f"[🔇 Ignored Phone Echo]: \"{transcript}\"")
                            cooldown_until = time.time() + 1.0
                            continue

                        if alt_transcript and alt_transcript.lower() != transcript.lower():
                            print(f"[📝 Caller Said (TA)]: \"{transcript}\"  |  (EN): \"{alt_transcript}\"")
                        else:
                            print(f"[📝 Caller Said]: \"{transcript}\"")

                        # Query Laptop 2 (/api/mobility/simulate) with primary + alternate transcript fallback
                        ai_reply = query_transit_laptop(transcript, session, alt_query_text=alt_transcript)
                        session.last_ai_reply = ai_reply

                        # Mute input stream via echo lock while AI speaks + 2.4s post-speech cellular cooldown
                        is_ai_speaking = True
                        try:
                            asyncio.run(speak_live(ai_reply, out_device_idx=out_idx, vac_out_idx=vac_out_idx))
                        finally:
                            audio_frames.clear()
                            pre_roll.clear()
                            cooldown_until = time.time() + POST_SPEECH_COOLDOWN
                            is_ai_speaking = False
                    else:
                        print("[ℹ️ Unclear audio / background noise — waiting for caller...]")
                except Exception as exc:
                    print(f"[⚠️ STT Error]: {exc}")

                print("🎙️ Listening for caller...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped Phone Link AI Agent.")
