"""Telegram Notification Integration for Chennai Mobility AI.

Posts live caller queries, structured route cards (Bus number, Arrival time / ETA,
Estimated drop time, Fare, Origin/Destination in Tamil & English), and the project
Logo (`backend/logo.png`) to Telegram Bot (@nampayanambot).

All networking runs asynchronously in a detached daemon thread so telephony audio
latency is 0ms.
"""
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import requests

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN", ""
)
# Target chat ID (pass via TELEGRAM_CHAT_ID env var, or dynamically discovered via /getUpdates)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Location of project logo
_DEFAULT_LOGO_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "backend", "logo.png")
)
if not os.path.exists(_DEFAULT_LOGO_PATH):
    _DEFAULT_LOGO_PATH = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "backend", "tests", "Logo.png")
    )


def get_latest_chat_id() -> str:
    """Discovers the active Telegram chat ID if not set."""
    global TELEGRAM_CHAT_ID
    if TELEGRAM_CHAT_ID:
        return str(TELEGRAM_CHAT_ID)
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        r = requests.get(url, timeout=3.0)
        if r.status_code == 200:
            updates = r.json().get("result", [])
            for u in reversed(updates):
                msg = u.get("message") or u.get("channel_post") or {}
                chat = msg.get("chat", {})
                if "id" in chat:
                    TELEGRAM_CHAT_ID = str(chat["id"])
                    return TELEGRAM_CHAT_ID
    except Exception:
        pass
    return "2126050420"


def calculate_estimated_drop_time(scheduled_arrival: str, stops_count: int, dist_km: float = 0.0) -> str:
    """Calculates approximate drop-off time based on scheduled arrival and travel time."""
    try:
        # Default transit speed in Chennai urban traffic ~ 15-18 km/h or ~2.5 mins per stop
        minutes_travel = int(stops_count * 2.8) if stops_count > 0 else (int(dist_km * 3.5) if dist_km > 0 else 25)
        minutes_travel = max(10, min(90, minutes_travel))

        if scheduled_arrival and ":" in scheduled_arrival:
            hh, mm = map(int, scheduled_arrival.strip().split(":")[:2])
            now = datetime.now()
            arr_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            drop_dt = arr_dt + timedelta(minutes=minutes_travel)
            return drop_dt.strftime("%I:%M %p")
        else:
            # Fallback relative to current time
            now = datetime.now()
            drop_dt = now + timedelta(minutes=minutes_travel + 15)
            return drop_dt.strftime("%I:%M %p")
    except Exception:
        return "N/A"


def format_telegram_card(
    caller_query: str,
    ai_response: str = "",
    backend_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Builds a rich, concise bilingual card with Bus, Arrival Time, Drop Time, and Stops."""
    backend_data = backend_data or {}
    options = backend_data.get("options") or []
    primary_opt = options[0] if options else {}
    legs = primary_opt.get("legs") or []
    leg = legs[0] if legs else {}

    # 1. Bus Route Number
    bus_number = leg.get("route") or ""
    if not bus_number:
        # Fallback extract from text
        match = re.search(r"\b(\d+[A-Za-z0-9]*)\b", ai_response)
        bus_number = match.group(1) if match else "MTC Bus"

    # 2. Origin & Destination Stops
    from_name = (leg.get("from_stop") or {}).get("name") or "Origin"
    to_name = (leg.get("to_stop") or {}).get("name") or "Destination"
    stops_count = leg.get("stops_count", 0)

    # 3. Arrival Estimate / ETA
    arrival = backend_data.get("arrival_estimate") or {}
    sched_time = arrival.get("scheduled_time") or ""
    eta_mins = arrival.get("eta_minutes")
    if sched_time:
        arrival_str = f"{sched_time} (in ~{eta_mins} mins)" if eta_mins else sched_time
    elif eta_mins:
        arrival_str = f"In ~{eta_mins} mins"
    else:
        arrival_str = "Frequent (5-10 mins)"

    # 4. Estimated Drop Time
    dist_val = (primary_opt.get("distance") or {}).get("value_km", 0.0)
    drop_time_str = calculate_estimated_drop_time(sched_time, stops_count, dist_val)

    # 5. Fare
    fare_info = primary_opt.get("fare") or {}
    fare_amt = fare_info.get("amount_inr")
    fare_str = f"₹{int(fare_amt)}" if fare_amt is not None else "Standard MTC fare"

    # Build brief bilingual markdown card
    lines = [
        f"🚍 *Chennai Transit Route Alert*",
        f"────────────────────────",
        f"🗣️ *Query / கேள்வி:* `{caller_query}`",
        f"🚌 *Bus Number / பேருந்து எண்:* *{bus_number}*",
        f"📍 *Route / வழி:* {from_name} ➔ {to_name}",
        f"⏱️ *Bus Arrival / வரும் நேரம்:* `{arrival_str}`",
        f"🏁 *Estimated Drop / சேரும் நேரம்:* `{drop_time_str}`",
        f"🛑 *Stops / நிறுத்தங்கள்:* {stops_count} stops" if stops_count else "",
        f"🎟️ *Fare / கட்டணம்:* {fare_str}",
        f"────────────────────────",
    ]

    # Filter out empty lines
    clean_lines = [l for l in lines if l]

    if ai_response:
        # Add a 1-sentence Tamil speech snippet
        ta_brief = ai_response.split(".")[0].strip() + "." if "." in ai_response else ai_response.strip()
        clean_lines.append(f"🔊 *Tamil:* _{ta_brief}_")

    return "\n".join(clean_lines)


def notify_telegram_async(
    caller_query: str,
    ai_response: str = "",
    backend_data: Optional[Dict[str, Any]] = None,
) -> None:
    """Non-blocking background notification.
    
    Sends a photo with the project Logo and structured route card.
    Never blocks or adds latency to the live phone call audio stream.
    """
    def _worker():
        chat_id = get_latest_chat_id()
        if not chat_id:
            return

        card_caption = format_telegram_card(caller_query, ai_response, backend_data)

        # Send photo with caption if logo exists
        if os.path.exists(_DEFAULT_LOGO_PATH):
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                with open(_DEFAULT_LOGO_PATH, "rb") as photo_file:
                    resp = requests.post(
                        url,
                        data={
                            "chat_id": chat_id,
                            "caption": card_caption,
                            "parse_mode": "Markdown",
                        },
                        files={"photo": photo_file},
                        timeout=8.0,
                    )
                if resp.status_code == 200:
                    return
            except Exception:
                pass

        # Fallback to text message if photo fails
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": card_caption,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=5.0,
            )
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()
