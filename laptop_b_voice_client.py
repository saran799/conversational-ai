"""Bridge client for Laptop B (the machine running the Voice AI / Model).

Flow:
1. Receives voice or text query in any language (English, Tamil, Tanglish).
2. Sends the query across the ngrok tunnel to Laptop A's Mobility Backend.
3. Receives structured route + spoken script text.
4. Feeds spoken text into local Voice Model (TTS).
5. Transmits synthesized audio back to Laptop A (Cellular / Phone line).
"""
import argparse
import json
import sys
import requests

# Laptop A IP on your shared Wi-Fi / Hotspot network:
DEFAULT_TRANSIT_SERVER_URL = "http://192.168.137.171:8000"


class VoiceModelBridge:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")
        self.endpoint = f"{self.server_url}/api/mobility/simulate"
        self.audio_return_endpoint = f"{self.server_url}/api/mobility/receive-voice"

    def process_incoming_query(self, query_text: str, language: str = "en"):
        """Send caller's transcribed query across local Wi-Fi to Laptop A."""
        print(f"\n[Laptop B (192.168.137.1)] Sending query to Laptop A (192.168.137.171:8000):")
        print(f"  • Query: '{query_text}'")
        print(f"  • Language: '{language}'")

        payload = {
            "query": query_text,
            "language": language,
        }

        try:
            resp = requests.post(self.endpoint, json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[Laptop B] Error calling Laptop A: {e}")
            return None

        status = data.get("status")
        speech_text = data.get("speech_text")
        follow_up = data.get("follow_up_question")
        detected_lang = data.get("language", language)

        print(f"\n[Laptop B] Response received from Laptop A:")
        print(f"  • Status: {status}")
        print(f"  • Spoken Script ({detected_lang.upper()}): \"{speech_text}\"")
        if follow_up:
            print(f"  • Follow-up: \"{follow_up}\"")

        # Hook into Local Voice Model on Laptop B
        full_text_to_speak = speech_text + (f" {follow_up}" if follow_up else "")
        audio_payload = self.synthesize_with_local_voice_model(full_text_to_speak, detected_lang)

        # Transmit synthesized voice audio back to Laptop A for cellular playback
        self.transmit_audio_to_laptop_a(audio_payload, session_id=data.get("session_id"))

        return data

    def synthesize_with_local_voice_model(self, text: str, language: str) -> bytes:
        """PLACEHOLDER: Hook your local voice model (TTS) here on Laptop B."""
        print(f"\n[Laptop B Voice Model] Synthesizing speech with local voice model...")
        print(f"  --> Text: \"{text}\"")
        print(f"  --> Language: {language}")

        # In your actual local model code on Laptop B:
        # audio_bytes = my_local_voice_model.generate_audio(text, language)
        # return audio_bytes
        mock_audio_bytes = b"RIFF....WAVEfmt....mock_audio_pcm_stream"
        print(f"[Laptop B Voice Model] Synthesized {len(mock_audio_bytes)} audio bytes.")
        return mock_audio_bytes

    def transmit_audio_to_laptop_a(self, audio_bytes: bytes, session_id: str = None):
        """Transmits synthesized audio back to Laptop A so it can play through the phone/cellular line."""
        print(f"[Laptop B] Transmitting audio stream back to Laptop A (Cellular Gateway)...")
        # In production, sends audio frames over WebSocket or HTTP back to Laptop A
        print(f"[Laptop B] Transmission complete. Ready for caller playback.")


def main():
    parser = argparse.ArgumentParser(description="Laptop B Voice Bridge Client")
    parser.add_argument("--url", default=DEFAULT_TUNNEL_URL, help="Laptop A ngrok tunnel URL")
    parser.add_argument("--query", default="போரூரில் இருந்து கிண்டி போகணும் என்ன பஸ் எடுக்கணும்", help="Spoken query text")
    parser.add_argument("--lang", default="ta", help="Language code ('ta' or 'en')")
    args = parser.parse_args()

    bridge = VoiceModelBridge(tunnel_url=args.url)
    bridge.process_incoming_query(query_text=args.query, language=args.lang)


if __name__ == "__main__":
    main()

