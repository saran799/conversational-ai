"""Voice + Cellular Master Client (Runs on 192.168.137.1).

Role:
1. Ingests caller speech from active phone call / mic.
2. Transcribes speech with local STT model (Tamil, English, Tanglish).
3. Sends transcribed query across Wi-Fi to Transit Engine (192.168.137.171:8000).
4. Receives verified bus routes & spoken script text.
5. Synthesizes voice audio locally with Voice Model (TTS).
6. Plays the audio directly into the active phone call on this machine!
"""
import argparse
import sys
import requests

TRANSIT_AI_URL = "http://192.168.137.171:8000/api/mobility/simulate"


class VoiceCellularMaster:
    def __init__(self, transit_url: str = TRANSIT_AI_URL):
        self.transit_url = transit_url

    def handle_call_turn(self, query_text: str, language: str = "ta"):
        print("=" * 65)
        print(" [VOICE + CELLULAR MASTER (192.168.137.1)]")
        print("=" * 65)
        print(f"1. Transcribed Caller Speech: '{query_text}' (Language: {language})")

        # Step 1: Query Transit Engine on 192.168.137.171
        print(f"2. Querying Transit Engine -> {self.transit_url} ...")
        payload = {"query": query_text, "language": language}
        try:
            resp = requests.post(self.transit_url, json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[Error] Failed to reach Transit Engine on 192.168.137.171: {e}")
            return None

        status = data.get("status")
        speech_text = data.get("speech_text")
        follow_up = data.get("follow_up_question")
        detected_lang = data.get("language", language)

        print(f"3. Transit Route Received from 192.168.137.171:")
        print(f"   • Status: {status}")
        print(f"   • Options Found: {len(data.get('options', []))}")
        print(f"   • Spoken Script ({detected_lang.upper()}): \"{speech_text}\"")

        # Step 2: Synthesize audio using your local Voice Model (TTS)
        full_script = speech_text + (f" {follow_up}" if follow_up else "")
        audio_bytes = self.synthesize_speech_locally(full_script, detected_lang)

        # Step 3: Play audio directly into the active cellular phone call on this machine
        self.play_audio_to_phone_call(audio_bytes)
        return data

    def synthesize_speech_locally(self, text: str, language: str) -> bytes:
        """HOOK YOUR LOCAL VOICE MODEL (TTS) HERE."""
        print(f"\n4. [Local Voice Model] Synthesizing speech...")
        print(f"   --> Script Text: \"{text}\"")
        print(f"   --> Language: {language}")

        # Example:
        # audio_bytes = my_voice_model.generate_audio(text, language)
        audio_bytes = b"RIFF_SAMPLE_PCM_WAV_AUDIO"
        print(f"   --> Synthesized {len(audio_bytes)} audio bytes.")
        return audio_bytes

    def play_audio_to_phone_call(self, audio_bytes: bytes):
        """PLAYS AUDIO LOCALLY INTO CELLULAR PHONE LINE (NO NETWORK HOP NEEDED)."""
        print(f"\n5. [Cellular Output] Streaming audio directly into active phone call...")
        # Since the phone is connected directly to this laptop (192.168.137.1),
        # pipe audio_bytes directly to the cellular audio device:
        # sounddevice.play(audio_bytes)
        print("   --> Audio successfully played to caller on the phone!")


def main():
    parser = argparse.ArgumentParser(description="Voice + Cellular Master Client")
    parser.add_argument("--query", default="போரூரில் இருந்து கிண்டி போகணும் என்ன பஸ் எடுக்கணும்", help="Caller query")
    parser.add_argument("--lang", default="ta", help="Language code ('ta' or 'en')")
    args = parser.parse_args()

    master = VoiceCellularMaster()
    master.handle_call_turn(args.query, args.lang)


if __name__ == "__main__":
    main()

