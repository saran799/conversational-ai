"""Android Termux / Tasker / Automate Telephony Companion Script.

Run this script on the Android Phone (via Termux or Termux:API / QPython):
When a call is answered (OFFHOOK), sends POST http://192.168.137.1:8080/call-started.
When the call ends (IDLE), sends POST http://192.168.137.1:8080/call-ended.

Requirements on Android (Termux):
    pkg install termux-api python
    pip install requests
    (Also install Termux:API from F-Droid or Play Store)
"""
import json
import subprocess
import time
import requests

LAPTOP_IP = "192.168.137.1"
WEBHOOK_PORT = 8080
START_URL = f"http://{LAPTOP_IP}:{WEBHOOK_PORT}/call-started"
END_URL = f"http://{LAPTOP_IP}:{WEBHOOK_PORT}/call-ended"

def get_telephony_state() -> str:
    """Uses termux-telephony-callinfo to get active call status."""
    try:
        proc = subprocess.run(["termux-telephony-callinfo"], capture_output=True, text=True, timeout=2.0)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            # CALL_STATE_OFFHOOK (answered), CALL_STATE_RINGING, CALL_STATE_IDLE
            return data.get("call_state", "CALL_STATE_IDLE")
    except Exception:
        pass
    return "CALL_STATE_IDLE"

def main():
    print("=" * 60)
    print(" 📱 ANDROID TELEPHONY COMPANION FOR CHENNAI MOBILITY AI")
    print(f" 🌐 Target Laptop Webhook: http://{LAPTOP_IP}:{WEBHOOK_PORT}")
    print("=" * 60)

    last_state = "CALL_STATE_IDLE"

    while True:
        current_state = get_telephony_state()
        if current_state != last_state:
            print(f"[State Change] {last_state} -> {current_state}")
            if current_state == "CALL_STATE_OFFHOOK":
                print(" -> Call ANSWERED! Notifying laptop...")
                try:
                    requests.post(START_URL, timeout=1.5)
                    print(" -> Sent POST /call-started (OK)")
                except Exception as e:
                    print(f" -> Failed to notify laptop: {e}")
            elif last_state == "CALL_STATE_OFFHOOK" and current_state == "CALL_STATE_IDLE":
                print(" -> Call ENDED! Notifying laptop...")
                try:
                    requests.post(END_URL, timeout=1.5)
                    print(" -> Sent POST /call-ended (OK)")
                except Exception as e:
                    print(f" -> Failed to notify laptop: {e}")

            last_state = current_state

        time.sleep(0.5)

if __name__ == "__main__":
    main()
