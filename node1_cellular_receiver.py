"""Node 1 Lightweight Audio Receiver (Cellular Laptop - 192.168.137.243).

Run this on the Cellular Laptop (192.168.137.243):
- Listens on port 8080.
- Receives synthesized audio from Node 2 (Voice Model Laptop - 192.168.137.1).
- Streams the audio into the phone call / audio output.
"""
from fastapi import FastAPI, Request
import uvicorn

app = FastAPI(title="Node 1 Cellular Audio Receiver")


@app.post("/audio/play")
async def play_audio_to_caller(request: Request):
    audio_bytes = await request.body()
    print(f"\n[Cellular Laptop] Received {len(audio_bytes)} audio bytes from Node 2.")
    print("[Cellular Laptop] Streaming audio into active phone call / headset...")
    # Hook cellular audio line / sound device playback here:
    # sounddevice.play(audio_bytes)
    return {"status": "playing", "bytes_received": len(audio_bytes)}


if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  NODE 1: CELLULAR AUDIO RECEIVER (192.168.137.243:8080)  ")
    print("=" * 65)
    print("Listening for synthesized voice from Node 2 (192.168.137.1)...")
    uvicorn.run(app, host="0.0.0.0", port=8080)

