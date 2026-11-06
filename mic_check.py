"""Live microphone level checker for the Phone Link bridge.

Shows a real-time loudness meter so you can see WHICH input device actually
hears your voice. Speak normally while each device is being tested.

Usage:
    python mic_check.py            # auto: tests current default input + Microphone Array (MME)
    python mic_check.py 3          # test only device index 3
    python mic_check.py 3 1 2      # test devices 3, then 1, then 2
"""
import os
import subprocess
import sys

# Match the bridge's behaviour: run under Python 3.11 where the audio stack is installed.
_PY311 = r"C:\Users\Nandheesaprasad\AppData\Local\Programs\Python\Python311\python.exe"
if os.path.exists(_PY311) and os.path.normcase(sys.executable) != os.path.normcase(_PY311):
    sys.exit(subprocess.call([_PY311, *sys.argv]))

import time
import numpy as np
import sounddevice as sd

SECONDS = 6.0
BRIDGE_THRESHOLD_FLOOR = 0.0065  # the clamp value seen in your calibration


def list_inputs():
    print("\n=== INPUT DEVICES ===")
    din, dout = sd.default.device
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "  <-- DEFAULT INPUT" if i == din else ""
            print(f"[{i:2}] hostapi={d['hostapi']}  {d['name']}{mark}")
    print(f"(default input index = {din}, default output index = {dout})\n")


def find_mic_array_mme():
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["hostapi"] == 0 and "microphone array" in d["name"].lower():
            return i
    return None


def meter(device_index):
    try:
        info = sd.query_devices(device_index)
    except Exception as exc:
        print(f"[device {device_index}] cannot query: {exc}")
        return
    name = info["name"]
    sr = int(info.get("default_samplerate") or 16000)
    print(f"\n----- Testing [{device_index}] {name} @ {sr} Hz -----")
    print("SPEAK NOW (loudly, a full sentence)...")

    peak = {"v": 0.0}
    rms_acc = {"sum": 0.0, "n": 0}

    def cb(indata, frames, t, status):
        block_peak = float(np.max(np.abs(indata))) if indata.size else 0.0
        block_rms = float(np.sqrt(np.mean(np.square(indata)))) if indata.size else 0.0
        peak["v"] = max(peak["v"], block_peak)
        rms_acc["sum"] += block_rms
        rms_acc["n"] += 1
        bars = int(min(1.0, block_rms * 8) * 40)
        sys.stdout.write("\r  [" + "#" * bars + "-" * (40 - bars) + f"] rms={block_rms:.4f}")
        sys.stdout.flush()

    try:
        with sd.InputStream(device=device_index, channels=1, samplerate=sr, dtype="float32", callback=cb):
            time.sleep(SECONDS)
    except Exception as exc:
        print(f"\n  [ERROR opening device {device_index}]: {exc}")
        return

    avg_rms = rms_acc["sum"] / max(1, rms_acc["n"])
    print(f"\n  RESULT: peak={peak['v']:.4f}  avg_rms={avg_rms:.4f}")
    if peak["v"] < 0.02:
        print("  VERDICT: SILENT — this device did NOT hear your voice.")
    elif avg_rms < BRIDGE_THRESHOLD_FLOOR:
        print("  VERDICT: very weak — below the bridge's trigger floor; raise mic level.")
    else:
        print("  VERDICT: GOOD — this device hears you. Use this index with --in-device.")


def main():
    list_inputs()
    args = [int(a) for a in sys.argv[1:] if a.lstrip("-").isdigit()]
    if args:
        targets = args
    else:
        din = sd.default.device[0]
        mic = find_mic_array_mme()
        targets = []
        if din is not None:
            targets.append(din)
        if mic is not None and mic not in targets:
            targets.append(mic)
    print(f"Will test devices: {targets}")
    for idx in targets:
        meter(idx)
    print("\nDone. Tell Claude the peak/avg_rms and VERDICT for each device.")


if __name__ == "__main__":
    main()
