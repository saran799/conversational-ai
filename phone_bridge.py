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

# ================= NETWORK & AUDIO CONFIGURATION =================
TRANSIT_LAPTOP_IP = os.environ.get("TRANSIT_LAPTOP_IP", "192.168.137.171")
TRANSIT_SIMULATE_URL = f"http://{TRANSIT_LAPTOP_IP}:8000/api/mobility/simulate"
TRANSIT_SEARCH_FALLBACK_URL = f"http://{TRANSIT_LAPTOP_IP}:8000/api/mobility/routes/search"
TRANSIT_TURN_FALLBACK_URL = f"http://{TRANSIT_LAPTOP_IP}:8000/api/voice/turn"

STT_SAMPLE_RATE = 16000
SILENCE_DURATION = 1.1       # Seconds of silence after speech to trigger transcription
MAX_UTTERANCE_SECONDS = 12.0 # Cap utterance length so noisy rooms never hang forever
POST_SPEECH_COOLDOWN = 0.5   # Cooldown after AI finishes speaking to prevent echo
# =================================================================

VOICES = {
    "ta": "ta-IN-PallaviNeural",  # Energetic, natural Tamil + English bilingual neural voice
    "en": "en-IN-NeerjaNeural",   # Warm Indian English female voice
}

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


def find_safe_phone_audio_devices() -> Tuple[int, str, int, int, str, Optional[int]]:
    """Configures Phone Link audio pipeline using Virtual Audio Cables:
    
    1. INCOMING AUDIO FROM PHONE LINK (Speaker part of Phone Link):
       - Captured via `Line 1 (Virtual Audio Cable)` [Input]
    2. OUTGOING AUDIO TO PHONE LINK (Mic part of Phone Link):
       - Injected via `Line 2 (Virtual Audio Cable)` [Output]
       - Also played through physical Speakers so you can hear what the AI says.
    """
    devices = sd.query_devices()
    default_in = sd.default.device[0] if sd.default.device[0] is not None else 1
    default_out = sd.default.device[1] if sd.default.device[1] is not None else 5

    line1_in_idx = None
    line2_out_idx = None
    speakers_out_idx = None

    for i, dev in enumerate(devices):
        name = dev["name"].lower()
        hostapi = int(dev.get("hostapi", 0))
        # Prefer MME (hostapi 0) or DirectSound (hostapi 1) or WASAPI (hostapi 2); avoid WDM-KS (-9999)
        if hostapi not in (0, 1, 2):
            continue

        if dev["max_input_channels"] > 0:
            if "line 1" in name and line1_in_idx is None:
                ok, _ = _can_open_input_device(i)
                if ok:
                    line1_in_idx = i

        if dev["max_output_channels"] > 0:
            if "line 2" in name and line2_out_idx is None:
                ok, _ = _can_open_output_device(i)
                if ok:
                    line2_out_idx = i
            elif "speaker" in name and speakers_out_idx is None:
                ok, _ = _can_open_output_device(i)
                if ok:
                    speakers_out_idx = i

    # Input: Specifically Line 1 (Virtual Audio Cable)
    if line1_in_idx is not None:
        chosen_in = line1_in_idx
    else:
        print("[⚠️ Notice] 'Line 1 (Virtual Audio Cable)' input not found, falling back to default mic.")
        chosen_in = default_in

    ok, chosen_in_sr = _can_open_input_device(chosen_in)
    if not ok:
        chosen_in, chosen_in_sr = 0, STT_SAMPLE_RATE
    chosen_in_name = devices[chosen_in]["name"]

    # Primary Output for caller: Line 2 (Virtual Audio Cable)
    # Secondary Output for operator monitoring: Physical Speakers
    if line2_out_idx is not None:
        chosen_out = line2_out_idx
    else:
        chosen_out = default_out
    chosen_out_name = devices[chosen_out]["name"]

    # Monitor output on physical speakers (or fallback)
    monitor_out_idx = speakers_out_idx if speakers_out_idx is not None else default_out

    return chosen_in, chosen_in_name, chosen_in_sr, chosen_out, chosen_out_name, monitor_out_idx


class ConversationSession:
    """Tracks multi-turn state with Worker 2's /api/mobility/simulate response options."""

    def __init__(self):
        self.session_id: str = f"sess_{int(time.time())}"
        self.last_options: List[Dict[str, Any]] = []
        self.option_cursor: int = 0
        self.last_language: str = "ta"
        self.awaiting_next_option_confirm: bool = False

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


def query_transit_laptop(query_text: str, session: ConversationSession) -> str:
    """Sends the exact commonized Request JSON to Laptop 2 (192.168.137.171:8000/api/mobility/simulate)
    and parses the exact Response JSON."""
    lang = detect_language(query_text)
    session.last_language = lang
    cleaned = query_text.strip()

    # 1. Handle pure greeting instantly
    if _GREETING_ONLY_RE.match(cleaned):
        if lang == "en":
            return "Hello! Welcome to Chennai Mobility AI. Where would you like to travel from and to today?"
        return "வணக்கம்! சென்னை மொபிலிட்டி AI-க்கு வரவேற்கிறோம். இன்னைக்கு நீங்க எங்கிருந்து எங்க போகணும்னு சொல்லுங்க?"

    # 2. Handle follow-up "Yes / ஆமா / அடுத்த வழித்தடம்" for cached options from previous turn
    if session.awaiting_next_option_confirm and len(cleaned.split()) <= 4:
        if _AFFIRMATIVE_RE.search(cleaned):
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

        if _NEGATIVE_RE.search(cleaned):
            session.awaiting_next_option_confirm = False
            return (
                "மிக்க நன்றி! உங்கள் பயணம் இனிதாகட்டும். வணக்கம்!"
                if lang == "ta"
                else "Thank you for using Chennai Mobility AI! Have a safe journey!"
            )

    # 3. Build exact Request JSON for Laptop 2: POST http://192.168.137.171:8000/api/mobility/simulate
    request_payload = {
        "query": cleaned,
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

            if data.get("session_id"):
                session.session_id = str(data["session_id"])

            speech_text = str(data.get("speech_text") or "").strip()
            follow_up = str(data.get("follow_up_question") or "").strip()
            options = data.get("options") or []

            session.last_options = options
            session.option_cursor = 1 if len(options) > 1 else len(options)
            session.awaiting_next_option_confirm = bool(follow_up and len(options) > 1)

            if speech_text:
                combined = f"{speech_text} {follow_up}".strip() if follow_up else speech_text
                return combined
    except requests.exceptions.RequestException as exc:
        print(f"[⚠️ Network Notice] Could not reach {TRANSIT_SIMULATE_URL}: {exc}")

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


async def speak_live(text: str, out_device_idx: Optional[int] = None, vac_out_idx: Optional[int] = None) -> None:
    """Synthesizes speech in memory and plays simultaneously to Speakers + Virtual Audio Cable / Phone Link."""
    lang = detect_language(text)
    voice_name = VOICES.get(lang, VOICES["ta"])
    rate = "+8%"
    pitch = "+5Hz" if lang == "ta" else "+0Hz"

    print(f"\n[🗣️ AI Speaking ({voice_name})]: \"{text}\"")
    communicate = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)

    audio_buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.extend(chunk["data"])

    if not audio_buffer:
        return

    mp3_bytes = bytes(audio_buffer)

    # Play on primary speakers via pygame mixer AND on Virtual Audio Cable (if present) via sounddevice
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(io.BytesIO(mp3_bytes))
        pygame.mixer.music.play()

        if vac_out_idx is not None:
            try:
                samples, sr_rate = sf.read(io.BytesIO(mp3_bytes), dtype="float32")
                sd.play(samples, samplerate=sr_rate, device=vac_out_idx, blocking=False)
            except Exception:
                pass

        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(15)
        pygame.mixer.music.unload()
        sd.stop()
    except Exception:
        # Fallback direct sounddevice playback
        samples, sr_rate = sf.read(io.BytesIO(mp3_bytes), dtype="float32")
        sd.play(samples, samplerate=sr_rate, device=out_device_idx, blocking=True)

    print("[✅ Finished speaking]\n")


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
    args = parser.parse_args()

    session = ConversationSession()

    if args.simulate:
        reply_text = query_transit_laptop(args.simulate, session)
        asyncio.run(speak_live(reply_text, out_device_idx=args.out_device))
        return

    in_idx, in_name, in_sr, out_idx, out_name, monitor_out_idx = find_safe_phone_audio_devices()
    if args.in_device is not None:
        in_idx = args.in_device
        in_name = sd.query_devices(in_idx)["name"]
    if args.out_device is not None:
        out_idx = args.out_device
        out_name = sd.query_devices(out_idx)["name"]

    print("=" * 72)
    print("   📞 CHENNAI MOBILITY AI — PHONE LINK VC ROUTED AGENT (FULL-DUPLEX)   ")
    print("=" * 72)
    print(f"👂 Caller Audio IN (Phone Link Spk -> Line 1 VC) : [{in_idx}] {in_name} ({in_sr} Hz)")
    print(f"🗣️ AI Voice OUT (Line 2 VC -> Phone Link Mic)   : [{out_idx}] {out_name}")
    if monitor_out_idx is not None and monitor_out_idx != out_idx:
        print(f"🔊 Room Monitor OUT (Speakers)                  : [{monitor_out_idx}] {sd.query_devices(monitor_out_idx)['name']}")
    print(f"🧠 Transit AI Endpoint                           : {TRANSIT_SIMULATE_URL}")
    print("=" * 72)

    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True

    # Calibrate ambient noise floor for 0.8s so room hum never false-triggers
    print("[🔧 Calibrating background noise level for 0.8s...]")
    ambient_rms = 0.0045
    try:
        calib_frames = int(0.8 * in_sr)
        rec = sd.rec(calib_frames, samplerate=in_sr, channels=1, dtype="float32", device=in_idx)
        sd.wait()
        measured = float(np.sqrt(np.mean(np.square(rec))))
        ambient_rms = max(0.0035, min(0.025, measured * 2.5))
    except Exception:
        ambient_rms = 0.0050
    print(f"[✅ Noise threshold calibrated: {ambient_rms:.4f}]")
    print("\n🎙️ Ready! Speak into the phone / mic (Press Ctrl+C to stop)...\n")

    audio_frames: List[np.ndarray] = []
    is_caller_speaking = False
    is_ai_speaking = False
    silence_start: Optional[float] = None
    utterance_start: Optional[float] = None
    cooldown_until: float = 0.0

    def audio_callback(indata, frames, time_info, status):
        nonlocal is_caller_speaking, silence_start, utterance_start
        # ECHO PREVENTION: Ignore mic input while AI is speaking or in cooldown
        if is_ai_speaking or time.time() < cooldown_until:
            return

        rms = float(np.sqrt(np.mean(np.square(indata))))
        now = time.time()

        if rms > ambient_rms:
            if not is_caller_speaking:
                print("\n[🎙️ Caller speaking...]", end="", flush=True)
                is_caller_speaking = True
                utterance_start = now
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

    with sd.InputStream(device=in_idx, channels=1, samplerate=in_sr, dtype="float32", callback=audio_callback):
        while True:
            time.sleep(0.08)
            min_frames_needed = max(3, int((in_sr * 0.4) / 512))
            if not is_caller_speaking and len(audio_frames) >= min_frames_needed:
                print(" [Transcribing...]")
                captured = np.concatenate(audio_frames, axis=0)
                audio_frames.clear()
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

                    transcript = ""
                    try:
                        transcript = recognizer.recognize_google(audio_data, language="ta-IN")
                    except sr.UnknownValueError:
                        try:
                            transcript = recognizer.recognize_google(audio_data, language="en-IN")
                        except sr.UnknownValueError:
                            transcript = ""

                    if transcript.strip():
                        print(f"[📝 Caller Said]: \"{transcript}\"")

                        # Query Laptop 2 (/api/mobility/simulate)
                        ai_reply = query_transit_laptop(transcript, session)

                        # Mute input stream via echo lock while AI speaks
                        is_ai_speaking = True
                        try:
                            asyncio.run(speak_live(ai_reply, out_device_idx=out_idx, vac_out_idx=monitor_out_idx))
                        finally:
                            audio_frames.clear()
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
