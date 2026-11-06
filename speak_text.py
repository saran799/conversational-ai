"""Interactive Multilingual AI Voice Reader.

Streams audio directly in memory and plays it live through your speakers
with ZERO disk saving and no external media player popups.
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
import edge_tts
import pygame

# Initialize pygame audio mixer for in-memory playback
pygame.mixer.init()

VOICES = {
    "ta": "ta-IN-PallaviNeural",       # Tamil (youthful, energetic, natural)
    "ta-male": "ta-IN-ValluvarNeural", # Tamil (Male)
    "en": "en-IN-NeerjaNeural",        # Indian English (Female)
    "en-male": "en-IN-PrabhatNeural",  # Indian English (Male)
    "hi": "hi-IN-SwaraNeural",         # Hindi (Female)
}


def detect_language(text: str) -> str:
    """Detect whether input contains Tamil characters."""
    for char in text:
        if "\u0b80" <= char <= "\u0bff":
            return "ta"
    return "en"


async def play_live_speech(text: str, voice_override: str = None):
    from phone_bridge import find_safe_phone_audio_devices, speak_live

    # find_safe_phone_audio_devices() applies the safe Phone Link comms-only routing internally
    # (once per process) — it no longer hijacks the default STT microphone.
    _, _, _, out_idx, _, vac_out_idx = find_safe_phone_audio_devices()
    await speak_live(text, out_device_idx=out_idx, vac_out_idx=vac_out_idx)


def main():
    parser = argparse.ArgumentParser(description="Live In-Memory Multilingual AI Voice Reader")
    parser.add_argument("--text", "-t", type=str, help="Text string to speak immediately")
    parser.add_argument("--file", "-f", type=str, help="Path to text file to read aloud")
    parser.add_argument("--lang", "-l", type=str, choices=list(VOICES.keys()), help="Force voice key")
    args = parser.parse_args()

    voice_override = VOICES.get(args.lang) if args.lang else None

    if args.file and os.path.exists(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            asyncio.run(play_live_speech(content, voice_override=voice_override))
        return

    if args.text:
        asyncio.run(play_live_speech(args.text.strip(), voice_override=voice_override))
        return

    print("=" * 60)
    print("      🎙️  LIVE AI VOICE READER (IN-MEMORY STREAMING)      ")
    print("=" * 60)
    print("Audio plays LIVE through speakers (no files saved to disk).")
    print("Type any text below and press [Enter].")
    print("Type 'exit' or 'q' to quit.\n")

    while True:
        try:
            user_text = input("Enter text > ").strip()
            if not user_text:
                continue
            if user_text.lower() in ("exit", "quit", "q"):
                print("\nGoodbye!")
                break

            asyncio.run(play_live_speech(user_text, voice_override=voice_override))
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n[Error] {e}\n")


if __name__ == "__main__":
    main()
