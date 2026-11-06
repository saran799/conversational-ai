"""Node 2 Bridge Client (Voice Model Laptop - 192.168.137.1).

Role:
- Receives transcribed text from its local STT (or microphone).
- Sends query across local Wi-Fi to Node 3 (192.168.137.171:8000).
- Receives verified transit routes & spoken script text.
- Generates speech audio with its local Voice Model (TTS).
- Transmits audio stream to Node 1 (192.168.137.243) to play into the phone call.
"""
import argparse
import sys
import requests

NODE_TRANSIT_AI_URL = "http://192.168.137.171:8000/api/mobility/simulate"
NODE_CELLULAR_AUDIO_URL = "http://192.168.137.243:8080/audio/play"


class VoiceModelBridge:
    def __init__(self, transit_url: str = NODE_TRANSIT_AI_URL, cellular_url: str = NODE_CELLULAR_AUDIO_URL):
        self.transit_url = transit_url
        self.cellular_url = cellular_url

    def handle_voice_turn(self, query_text: str, language: str = "ta"):
        print("=" * 65)
        print("  [NODE 2: VOICE MODEL LAPTOP (192.168.137.1)]")
        print("=" * 65)
        print(f"1. Transcribed Query: '{query_text}' (Language: {language})")

        # Step 1: Send query to Node 3 (192.168.137.171) for transit reasoning
        print(f"2. Querying Node 3 Transit Engine -> {self.transit_url} ...")
        payload = {"query": query_text, "language": language}
        try:
            resp = requests.post(self.transit_url, json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[Error] Failed to reach Node 3 Transit Engine: {e}")
            return None

        status = data.get("status")
        speech_text = data.get("speech_text")
        follow_up = data.get("follow_up_question")
        detected_lang = data.get("language", language)

        print(f"3. Received from Node 3 Transit AI:")
        print(f"   • Status: {status}")
        print(f"   • Options Found: {len(data.get('options', []))}")
        print(f"   • Spoken Script: \"{speech_text}\"")

        # Step 2: Synthesize speech using Local Voice Model (TTS) on Node 2
        full_text = speech_text + (f" {follow_up}" if follow_up else "")
        audio_bytes = self.generate_tts(full_text, detected_lang)

        # Step 3: Stream audio to Node 1 (192.168.137.243) for Cellular Playback
        self.send_audio_to_cellular_laptop(audio_bytes)
        return data

    def generate_tts(self, text: str, language: str) -> bytes:
        """HOOK LOCAL TTS VOICE MODEL HERE ON NODE 2."""
        print(f"\n4. [Local TTS Model on Node 2] Synthesizing speech...")
        print(f"   --> Script Text: \"{text}\"")
        print(f"   --> Voice Language: {language}")

        # Hook your model:
        # audio_bytes = my_local_voice_model.generate_wav(text, language)
        audio_bytes = b"RIFF_SAMPLE_PCM_WAV_AUDIO_STREAM"
        print(f"   --> Generated {len(audio_bytes)} audio bytes.")
        return audio_bytes

    def send_audio_to_cellular_laptop(self, audio_bytes: bytes):
        """Sends generated audio to Node 1 (192.168.137.243) for phone call playback."""
        print(f"\n5. Streaming audio to Node 1 (Cellular Laptop - {self.cellular_url})...")
        try:
            headers = {"Content-Type": "audio/wav"}
            resp = requests.post(self.cellular_url, data=audio_bytes, headers=headers, timeout=2)
            print(f"   [Success] Audio delivered to Cellular Laptop (HTTP {resp.status_code}).")
        except Exception as e:
            print(f"   [Notice] Ready to stream to Cellular Laptop (Target: {self.cellular_url}): {e}")


def main():
    parser = argparse.ArgumentParser(description="Node 2 Voice Model Bridge")
    parser.add_argument("--query", default="போரூரில் இருந்து கிண்டி போகணும் என்ன பஸ் எடுக்கணும்", help="Query text")
    parser.add_argument("--lang", default="ta", help="Language code")
    args = parser.parse_args()

    bridge = VoiceModelBridge()
    bridge.handle_voice_turn(args.query, args.lang)


if __name__ == "__main__":
    main()

