import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.db.database import get_db
from app.models.campaign import CampaignCreate, DEFAULT_SEQUENCE
from app.services.ai import personalize_email
from app.services.gmail import send_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/campaigns", tags=["campaigns"])


# ---------- Models ----------

class AddLeadsToCampaign(BaseModel):
    lead_ids: list[str]
    schedule_start: Optional[str] = None   # ISO datetime, defaults to now


class ApproveEmail(BaseModel):
    email_id: str
    subject: Optional[str] = None
    body: Optional[str] = None
    scheduled_at: Optional[str] = None
    attach_resume: Optional[bool] = None


class SendNowRequest(BaseModel):
    attach_resume: bool = False
    scheduled_at: Optional[str] = None


# ---------- Helpers ----------

def _now():
    return datetime.now(timezone.utc)


def _default_sequence_dicts():
    return [s.model_dump() for s in DEFAULT_SEQUENCE]


def _step_config(sequence: list[dict], step: int) -> dict:
    for s in sequence:
        if s.get("step") == step:
            return s
    return {}


# ---------- Routes ----------

@router.post("/")
async def create_campaign(data: CampaignCreate):
    """Create a campaign with a per-step sequence."""
    db = get_db()

    sequence = [s.model_dump() for s in (data.sequence or DEFAULT_SEQUENCE)]
    # keep follow_up_days populated for older UI bits that still read it
    follow_up_days = [s["delay_days"] for s in sequence if s["step"] > 1]

    result = db.table("campaigns").insert({
        "name": data.name,
        "status": "draft",
        "sequence": sequence,
        "follow_up_days": follow_up_days,
        "resume_filename": data.resume_filename,
    }).execute()
    return result.data[0]


@router.get("/")
async def get_campaigns():
    """List all campaigns."""
    db = get_db()
    result = db.table("campaigns").select("*").order("created_at", desc=True).execute()
    return result.data


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Get a single campaign with all emails."""
    db = get_db()
    campaign = db.table("campaigns").select("*").eq("id", campaign_id).execute()
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")

    emails = db.table("emails")\
        .select("*, leads(name, title, company, email, score)")\
        .eq("campaign_id", campaign_id)\
        .order("created_at", desc=True)\
        .execute()

    return {**campaign.data[0], "emails": emails.data}


@router.post("/{campaign_id}/leads")
async def add_leads_to_campaign(campaign_id: str, data: AddLeadsToCampaign):
    """
    Add leads to a campaign and generate the step-1 email per lead
    (saved as pending_approval). Whether step 1 attaches a resume is
    decided by the campaign's sequence — not by this request.
    """
    db = get_db()

    campaign = db.table("campaigns").select("*").eq("id", campaign_id).execute()
    if not campaign.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = campaign.data[0]

    sequence = campaign.get("sequence") or _default_sequence_dicts()
    step1 = _step_config(sequence, 1)

    start_time = _now()
    if data.schedule_start:
        start_time = datetime.fromisoformat(data.schedule_start)
    start_time = start_time + timedelta(days=int(step1.get("delay_days", 0)))

    previews = []

    for lead_id in data.lead_ids:
        lead = db.table("leads").select("*").eq("id", lead_id).execute()
        if not lead.data:
            continue
        lead = lead.data[0]

        if not lead.get("email"):
            logger.warning(f"Lead {lead_id} has no email, skipping")
            continue

        existing = db.table("emails")\
            .select("id")\
            .eq("lead_id", lead_id)\
            .eq("campaign_id", campaign_id)\
            .execute()
        if existing.data:
            logger.info(f"Lead {lead_id} already in campaign, skipping")
            continue

        try:
            personalized = personalize_email(
                lead_name=lead["name"],
                lead_title=lead.get("title", ""),
                lead_company=lead.get("company", ""),
                sequence_step=1
            )

            result = db.table("emails").insert({
                "lead_id": lead_id,
                "campaign_id": campaign_id,
                "subject": personalized["subject"],
                "body": personalized["body"],
                "status": "pending_approval",
                "sequence_step": 1,
                "scheduled_at": start_time.isoformat(),
                "attach_resume": bool(step1.get("attach_resume", False)),
            }).execute()

            previews.append({
                "lead": {
                    "id": lead_id,
                    "name": lead["name"],
                    "title": lead.get("title"),
                    "company": lead.get("company"),
                    "email": lead["email"]
                },
                "email": result.data[0]
            })

        except Exception as e:
            logger.error(f"Failed to generate email for lead {lead_id}: {e}")
            continue

    return {
        "message": f"Generated {len(previews)} email previews",
        "previews": previews
    }


@router.get("/{campaign_id}/approvals")
async def get_pending_approvals(campaign_id: str):
    """Get all emails waiting for approval."""
    db = get_db()
    result = db.table("emails")\
        .select("*, leads(name, title, company, email, linkedin_url)")\
        .eq("campaign_id", campaign_id)\
        .eq("status", "pending_approval")\
        .execute()
    return result.data


@router.post("/approve/{email_id}")
async def approve_email(email_id: str, data: ApproveEmail):
    """Approve an email before sending. Optionally override fields."""
    db = get_db()

    email = db.table("emails").select("*").eq("id", email_id).execute()
    if not email.data:
        raise HTTPException(status_code=404, detail="Email not found")

    update_data = {"status": "pending"}
    if data.subject:
        update_data["subject"] = data.subject
    if data.body:
        update_data["body"] = data.body
    if data.scheduled_at:
        update_data["scheduled_at"] = data.scheduled_at
    if data.attach_resume is not None:
        update_data["attach_resume"] = data.attach_resume

    result = db.table("emails").update(update_data).eq("id", email_id).execute()
    return {"message": "Email approved and queued", "email": result.data[0]}


@router.post("/approve-all/{campaign_id}")
async def approve_all_emails(campaign_id: str):
    """Approve all pending emails in a campaign at once."""
    db = get_db()
    result = db.table("emails")\
        .update({"status": "pending"})\
        .eq("campaign_id", campaign_id)\
        .eq("status", "pending_approval")\
        .execute()
    return {"message": f"Approved {len(result.data)} emails"}


@router.post("/send-now/{email_id}")
async def send_email_now(email_id: str, data: SendNowRequest = SendNowRequest()):
    """Send a single email immediately or schedule it for a specific time."""
    db = get_db()

    email = db.table("emails").select("*, leads(*)").eq("id", email_id).execute()
    if not email.data:
        raise HTTPException(status_code=404, detail="Email not found")

    email = email.data[0]
    lead = email.get("leads", {})

    if not lead or not lead.get("email"):
        raise HTTPException(status_code=400, detail="Lead has no email address")

    if data.scheduled_at:
        db.table("emails").update({
            "status": "pending",
            "scheduled_at": data.scheduled_at,
            "attach_resume": data.attach_resume
        }).eq("id", email_id).execute()
        return {"message": f"Email scheduled for {data.scheduled_at}"}

    thread_id = None
    if email["sequence_step"] > 1:
        first = db.table("emails")\
            .select("gmail_thread_id")\
            .eq("lead_id", email["lead_id"])\
            .eq("sequence_step", 1)\
            .execute()
        if first.data:
            thread_id = first.data[0].get("gmail_thread_id")

    try:
        resume_filename = None
        if data.attach_resume or email.get("attach_resume", False):
            campaign = db.table("campaigns").select("resume_filename").eq("id", email["campaign_id"]).execute()
            if campaign.data:
                resume_filename = campaign.data[0].get("resume_filename")

        result = send_email(
            to=lead["email"],
            subject=email["subject"],
            body=email["body"],
            thread_id=thread_id,
            resume_filename=resume_filename,
            email_id=email_id
        )

        db.table("emails").update({
            "status": "sent",
            "sent_at": _now().isoformat(),
            "gmail_message_id": result["gmail_message_id"],
            "gmail_thread_id": result["gmail_thread_id"],
        }).eq("id", email_id).execute()

        db.table("leads").update({"status": "contacted"}).eq("id", lead["id"]).execute()

        return {"message": "Email sent", "result": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Send failed: {str(e)}")


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str):
    """Delete a campaign and all its emails."""
    db = get_db()
    db.table("emails").delete().eq("campaign_id", campaign_id).execute()
    db.table("campaigns").delete().eq("id", campaign_id).execute()
    return {"message": "Campaign deleted"}


@router.patch("/{campaign_id}/status")
async def update_campaign_status(campaign_id: str, status: str):
    """Pause or activate a campaign."""
    if status not in ["active", "paused", "completed"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    db = get_db()
    result = db.table("campaigns").update({"status": status}).eq("id", campaign_id).execute()
    return result.data[0]