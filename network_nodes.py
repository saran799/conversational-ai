"""Dual-Node Network Architecture Configuration.

Node Topology:
1. Node A (Voice Model + Cellular Laptop): 192.168.137.1
   - Cellular / Phone call audio interface
   - Runs STT (transcribes incoming caller audio)
   - Runs TTS (synthesizes Tamil/English voice audio)
   - Plays synthesized audio directly into the active phone call locally!
2. Node B (This Machine - AI Transit Backend): 192.168.137.171
   - SQLite Transit Database (MTC, CMRL, Suburban)
   - Stop Resolver, Routing Engine, Fare, Distance, Advisories, Speech Formatter
   - Serves API on: http://192.168.137.171:8000/api/mobility/simulate
"""

NODE_VOICE_CELLULAR_IP = "192.168.137.1"
NODE_TRANSIT_AI_IP = "192.168.137.171"

TRANSIT_API_URL = f"http://{NODE_TRANSIT_AI_IP}:8000/api/mobility/simulate"
