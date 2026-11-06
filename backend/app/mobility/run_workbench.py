"""Standalone runner for the Terminal Voice Workbench.
Starts a dedicated web server on port 8000 with the workbench and mobility API.
Open http://localhost:8000 in your browser to talk and listen with your Bluetooth headset.
"""
import os
import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from backend.app.mobility.router import router as mobility_router

app = FastAPI(title="Chennai Mobility AI - Terminal Voice Workbench")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mobility_router)


@app.get("/", response_class=HTMLResponse)
def index():
    html_path = os.path.join(os.path.dirname(__file__), "templates", "workbench.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Workbench HTML template not found.</h1>"


if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  CHENNAI MOBILITY AI - TERMINAL VOICE WORKBENCH SERVER  ")
    print("=" * 65)
    print("Serving interactive terminal UI on all interfaces on port 8000:")
    print("  • Localhost : http://127.0.0.1:8000")
    print("  • LAN / WiFi: http://192.168.137.171:8000")
    print("Press CTRL+C to stop the server.\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

