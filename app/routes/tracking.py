import logging
import base64
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import Response
from app.db.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/track", tags=["tracking"])

# 1x1 transparent GIF
PIXEL = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)


@router.get("/open/{email_id}")
async def track_open(email_id: str):
    """
    Called when recipient opens the email.
    Records open time in Supabase and returns a 1x1 transparent pixel.
    """
    try:
        db = get_db()
        email = db.table("emails").select("id, opened_at").eq("id", email_id).execute()

        if email.data and not email.data[0].get("opened_at"):
            db.table("emails").update({
                "opened_at": datetime.utcnow().isoformat(),
                "status": "opened"
            }).eq("id", email_id).execute()
            logger.info(f"Email opened: {email_id}")

    except Exception as e:
        logger.error(f"Tracking error for {email_id}: {e}")

    # Always return the pixel regardless of errors
    return Response(
        content=PIXEL,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache"
        }
    )


@router.get("/stats/{campaign_id}")
async def get_campaign_stats(campaign_id: str):
    """Get open/reply stats for a campaign."""
    db = get_db()
    emails = db.table("emails")\
        .select("status, opened_at, replied_at, sent_at")\
        .eq("campaign_id", campaign_id)\
        .execute()

    data = emails.data
    total = len(data)
    sent = len([e for e in data if e["sent_at"]])
    opened = len([e for e in data if e["opened_at"]])
    replied = len([e for e in data if e["replied_at"]])

    return {
        "total": total,
        "sent": sent,
        "opened": opened,
        "replied": replied,
        "open_rate": round(opened / sent * 100, 1) if sent else 0,
        "reply_rate": round(replied / sent * 100, 1) if sent else 0,
    }