"""Dedicated Voice Streaming & Phone Playback Microservice (192.168.137.1:8000).

Commonized to accept BOTH:
1. Simple text payload: {"text": "...", "language": "ta"}
2. Full Transit Laptop (192.168.137.171) /api/mobility/simulate response JSON:
   {
     "status": "OK",
     "language": "ta",
     "speech_text": "Porur முதல் Guindy Bus Terminus வரை நேரடி பேருந்து 88R உள்ளது...",
     "follow_up_question": "அடுத்த வழித்தடத்தைப் பற்றி தெரிந்து கொள்ள விரும்புகிறீர்களா?",
     "options": [...],
     "session_id": "..."
   }
"""
import os
import subprocess
import sys

# Auto-relaunch with Python 3.11 if invoked from Python 3.14 / another interpreter
_PY311 = r"C:\Users\Nandheesaprasad\AppData\Local\Programs\Python\Python311\python.exe"
if os.path.exists(_PY311) and os.path.normcase(sys.executable) != os.path.normcase(_PY311):
    sys.exit(subprocess.call([_PY311, *sys.argv]))

import io
from typing import Any, AsyncGenerator, Dict, List, Optional
import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Chennai Mobility AI - Live Voice Synthesizer", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VOICES = {
    "ta": "ta-IN-PallaviNeural",       # Tamil (youthful, energetic, natural)
    "ta-male": "ta-IN-ValluvarNeural", # Tamil (Male)
    "en": "en-IN-NeerjaNeural",        # Indian English (Female)
    "en-male": "en-IN-PrabhatNeural",  # Indian English (Male)
    "hi": "hi-IN-SwaraNeural",         # Hindi (Female)
}


def detect_language(text: str) -> str:
    for char in text:
        if "\u0b80" <= char <= "\u0bff":
            return "ta"
    return "en"


class CommonizedVoicePayload(BaseModel):
    """Accepts both simple {'text': ...} and Laptop 2's /api/mobility/simulate JSON."""
    text: Optional[str] = None
    speech_text: Optional[str] = None
    follow_up_question: Optional[str] = None
    language: Optional[str] = None
    status: Optional[str] = None
    data_status: Optional[str] = None
    options: Optional[List[Dict[str, Any]]] = None
    advisories: Optional[List[Any]] = None
    caveats: Optional[List[str]] = None
    session_id: Optional[str] = None
    rate: Optional[str] = "+8%"
    pitch: Optional[str] = "+5Hz"
    play_on_device: bool = False

    def resolved_speech_text(self) -> str:
        parts = []
        if self.speech_text and self.speech_text.strip():
            parts.append(self.speech_text.strip())
        elif self.text and self.text.strip():
            parts.append(self.text.strip())
        if self.follow_up_question and self.follow_up_question.strip():
            parts.append(self.follow_up_question.strip())
        return " ".join(parts).strip()


def _play_bytes_locally(audio_bytes: bytes) -> None:
    """Plays MP3 bytes directly in memory through pygame mixer."""
    try:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        stream = io.BytesIO(audio_bytes)
        pygame.mixer.music.load(stream)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(15)
        pygame.mixer.music.unload()
    except Exception as exc:
        print(f"[VoiceService] Local playback error: {exc}")


async def generate_audio_stream(
    text: str,
    voice_name: str,
    rate: str = "+8%",
    pitch: str = "+5Hz",
    play_locally: bool = False,
) -> AsyncGenerator[bytes, None]:
    """Streams audio chunks in real-time without touching the hard drive."""
    communicate = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)
    buffer = bytearray() if play_locally else None
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            data = chunk["data"]
            if buffer is not None:
                buffer.extend(data)
            yield data
    if buffer:
        _play_bytes_locally(bytes(buffer))


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "Voice Streaming Synthesizer",
        "ip": "192.168.137.1",
        "transit_backend": "http://192.168.137.171:8000/api/mobility/simulate",
    }


@app.post("/stream-voice")
async def stream_voice(req: CommonizedVoicePayload):
    """Accepts either {'text': ...} or Laptop 2's {'speech_text': ..., 'follow_up_question': ...}
    and returns a live HTTP audio/mpeg stream."""
    spoken = req.resolved_speech_text()
    if not spoken:
        raise HTTPException(status_code=400, detail="Neither 'text' nor 'speech_text' was provided.")

    lang = req.language or detect_language(spoken)
    if lang not in VOICES:
        lang = detect_language(spoken)
    voice_name = VOICES.get(lang, VOICES["ta"])

    pitch = req.pitch if lang == "ta" else "+0Hz"
    rate = req.rate or "+8%"

    return StreamingResponse(
        generate_audio_stream(
            spoken,
            voice_name,
            rate=rate,
            pitch=pitch,
            play_locally=req.play_on_device,
        ),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
            "Transfer-Encoding": "chunked",
            "X-Voice-Used": voice_name,
        },
    )


@app.post("/speak-to-phone")
async def speak_to_phone_endpoint(req: CommonizedVoicePayload):
    """Receives JSON from Laptop 2 and immediately plays the voice out loud on this laptop / Phone Link."""
    spoken = req.resolved_speech_text()
    if not spoken:
        raise HTTPException(status_code=400, detail="Neither 'text' nor 'speech_text' was provided.")

    lang = req.language or detect_language(spoken)
    if lang not in VOICES:
        lang = detect_language(spoken)
    voice_name = VOICES.get(lang, VOICES["ta"])
    pitch = req.pitch if lang == "ta" else "+0Hz"
    rate = req.rate or "+8%"

    communicate = edge_tts.Communicate(spoken, voice_name, rate=rate, pitch=pitch)
    audio_buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.extend(chunk["data"])

    _play_bytes_locally(bytes(audio_buffer))
    return {
        "status": "spoken",
        "voice": voice_name,
        "language": lang,
        "spoken_text": spoken,
        "session_id": req.session_id,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
