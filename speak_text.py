"""Interactive Multilingual AI Voice Reader.

Streams audio directly in memory and plays it live through your speakers
with ZERO disk saving and no external media player popups.
"""
import asyncio
import io
import os
import sys
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
    lang = detect_language(text)
    voice_name = voice_override or VOICES.get(lang, VOICES["ta"])
    
    # Fast, natural, conversational cadence
    rate = "+8%"
    pitch = "+5Hz" if lang == "ta" else "+0Hz"
    
    print(f"\n[Voice: {voice_name}] Synthesizing live in memory...")
    communicate = edge_tts.Communicate(text, voice_name, rate=rate, pitch=pitch)
    
    # Collect audio stream directly into RAM buffer (zero disk writes)
    audio_buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.extend(chunk["data"])
            
    # Play directly from memory buffer
    audio_stream = io.BytesIO(audio_buffer)
    pygame.mixer.music.load(audio_stream)
    pygame.mixer.music.play()
    
    print("[Speaking live...]")
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
    print("[Finished speaking]\n")

def main():
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
                
            asyncio.run(play_live_speech(user_text))
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\n[Error] {e}\n")

if __name__ == "__main__":
    main()
