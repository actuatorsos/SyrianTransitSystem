"""
Traccar GPS webhook routes: position updates and event handling.
Secured by HMAC-SHA256 signature verification.
"""

import os
import hashlib
import hmac
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from lib.database import get_db
from api.models import TraccarPosition, TraccarEvent

logger = logging.getLogger("damascus_transit")

router = APIRouter(prefix="/api/traccar", tags=["Traccar GPS"])

TRACCAR_WEBHOOK_SECRET = os.getenv("TRACCAR_WEBHOOK_SECRET", "")


def verify_traccar_signature(request_body: str, signature: str) -> bool:
    """Verify Traccar webhook HMAC-SHA256 signature."""
    if not TRACCAR_WEBHOOK_SECRET:
        return True  # Skip verification if no secret configured

    computed = hmac.new(
        TRACCAR_WEBHOOK_SECRET.encode(), request_body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


@router.post("/position")
async def traccar_position_webhook(
    position: TraccarPosition,
    x_traccar_signature: Optional[str] = None,
):
    """
    Webhook for Traccar GPS position updates.
    Maps Traccar device IDs to DamascusTransit vehicles and upserts positions.
    """
    if TRACCAR_WEBHOOK_SECRET and x_traccar_signature:
        if not verify_traccar_signature(position.json(), x_traccar_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    db = get_db()

    try:
        device_result = (
            db.table("vehicles")
            .select("id, vehicle_id")
            .eq("gps_device_id", str(position.deviceId))
            .execute()
        )

        if not device_result.data:
            logger.info(f"Traccar device {position.deviceId} not mapped to any vehicle")
            return {"status": "ignored", "reason": "device_not_found"}

        vehicle = device_result.data[0]

        db.rpc(
            "upsert_vehicle_position",
            {
                "p_vehicle_id": vehicle["id"],
                "p_lat": position.latitude,
                "p_lon": position.longitude,
                "p_speed": position.speed or 0,
                "p_heading": position.heading or 0,
                "p_source": "traccar",
                "p_route_id": None,
                "p_occupancy": None,
            },
        ).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except Exception as e:
        logger.error(f"Traccar position webhook error: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


@router.post("/event")
async def traccar_event_webhook(
    event: TraccarEvent,
    x_traccar_signature: Optional[str] = None,
):
    """
    Webhook for Traccar events (speeding, geofence, offline, etc).
    Critical events automatically generate alerts in the system.
    """
    if TRACCAR_WEBHOOK_SECRET and x_traccar_signature:
        if not verify_traccar_signature(event.json(), x_traccar_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    db = get_db()

    try:
        device_result = (
            db.table("vehicles")
            .select("id")
            .eq("gps_device_id", str(event.deviceId))
            .execute()
        )

        if not device_result.data:
            return {"status": "ignored", "reason": "device_not_found"}

        vehicle_id = device_result.data[0]["id"]

        # Map Traccar event types to our alert types
        event_type_map = {
            "motion": "speeding",
            "overspeed": "speeding",
            "geofenceEnter": "geofence_enter",
            "geofenceExit": "geofence_exit",
            "deviceOffline": "offline",
            "deviceOnline": "online",
        }

        alert_type = event_type_map.get(event.type, event.type)

        # Create alert for critical events
        critical_events = ["overspeed", "geofenceExit", "deviceOffline"]

        if event.type in critical_events:
            severity_map = {
                "overspeed": "high",
                "geofenceExit": "medium",
                "deviceOffline": "medium",
            }

            alert_data = {
                "vehicle_id": vehicle_id,
                "alert_type": alert_type,
                "severity": severity_map.get(event.type, "medium"),
                "title": f"Alert: {event.type} — {event.deviceName}",
                "title_ar": f"تنبيه: {event.type} — {event.deviceName}",
                "description": f"Traccar event: {event.data}",
                "is_resolved": False,
            }

            db.table("alerts").insert([alert_data]).execute()

            logger.warning(
                f"Alert created: {event.type} for vehicle {vehicle_id} (device: {event.deviceName})"
            )

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except Exception as e:
        logger.error(f"Traccar event webhook error: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}
