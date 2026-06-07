import os
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.db.database import get_db
from app.services.gmail import send_email, get_gmail_service
from app.services.ai import personalize_email

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# ---------------- Good-practice sending rules ----------------
# Cold emails land best on weekdays during business hours and bursts
# look spammy. The scheduler only sends inside this window and caps
# how many go out per run.
SEND_TZ = ZoneInfo("America/Toronto")
SEND_DAYS = {0, 1, 2, 3, 4}     # Mon–Fri
SEND_START_HOUR = 8             # 8:00 am ET
SEND_END_HOUR = 18              # 6:00 pm ET
MAX_SENDS_PER_RUN = 10

# Set IGNORE_SEND_WINDOW=true in .env to bypass the business-hours gate
# (useful for local testing).
IGNORE_WINDOW = os.getenv("IGNORE_SEND_WINDOW", "").lower() == "true"

# Fallback if a campaign somehow has no sequence saved.
DEFAULT_SEQUENCE = [
    {"step": 1, "delay_days": 0, "attach_resume": False},
    {"step": 2, "delay_days": 2, "attach_resume": True},
]


def _now():
    return datetime.now(timezone.utc)


def in_send_window() -> bool:
    if IGNORE_WINDOW:
        return True
    local = datetime.now(SEND_TZ)
    if local.weekday() not in SEND_DAYS:
        return False
    return SEND_START_HOUR <= local.hour < SEND_END_HOUR


def get_sequence(campaign: dict) -> list[dict]:
    return campaign.get("sequence") or DEFAULT_SEQUENCE


def step_config(sequence: list[dict], step: int) -> dict:
    for s in sequence:
        if s.get("step") == step:
            return s
    return {}


def has_real_reply(service, thread_id: str, my_email: str) -> bool:
    """
    True only if the thread contains a message NOT sent by us.
    (Counting messages > 1 wrongly flags our own follow-ups as replies.)
    """
    thread = service.users().threads().get(
        userId="me",
        id=thread_id,
        format="metadata",
        metadataHeaders=["From"],
    ).execute()

    for msg in thread.get("messages", []):
        headers = msg.get("payload", {}).get("headers", [])
        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
        if my_email.lower() not in sender.lower():
            return True
    return False


def thread_subject(original: str) -> str:
    """Force follow-ups onto the same Gmail thread by reusing the subject."""
    if not original:
        return "Re: (no subject)"
    if original.lower().startswith("re:"):
        return original
    return f"Re: {original}"


async def process_due_emails():
    """
    Runs on an interval:
      1. Detect real replies on sent threads and stop the sequence.
      2. During business hours, send due emails (resume attached per step).
      3. Schedule the next step from the campaign's sequence.
    """
    logger.info("Scheduler: checking emails...")
    db = get_db()

    # ---------- 1. Reply detection ----------
    service = None
    my_email = None
    try:
        service = get_gmail_service()
        my_email = service.users().getProfile(userId="me").execute().get("emailAddress", "")
    except Exception as e:
        logger.warning(f"Gmail unavailable, skipping reply check: {e}")

    if service and my_email:
        sent_emails = db.table("emails")\
            .select("*")\
            .eq("status", "sent")\
            .not_.is_("gmail_thread_id", "null")\
            .execute()

        for email in sent_emails.data:
            try:
                if has_real_reply(service, email["gmail_thread_id"], my_email):
                    logger.info(f"Real reply detected for lead {email['lead_id']}")
                    db.table("emails")\
                        .update({"status": "replied", "replied_at": _now().isoformat()})\
                        .eq("id", email["id"])\
                        .execute()
                    db.table("leads")\
                        .update({"status": "replied"})\
                        .eq("id", email["lead_id"])\
                        .execute()
                    # cancel any pending follow-ups for this lead
                    db.table("emails")\
                        .update({"status": "cancelled"})\
                        .eq("lead_id", email["lead_id"])\
                        .eq("status", "pending")\
                        .execute()
            except Exception as e:
                logger.error(f"Reply check failed for email {email['id']}: {e}")

    # ---------- 2. Respect the send window ----------
    if not in_send_window():
        logger.info("Outside send window (Mon–Fri 8am–6pm ET) — not sending this cycle.")
        return

    # ---------- 3. Send due emails ----------
    due = db.table("emails")\
        .select("*, leads(*)")\
        .eq("status", "pending")\
        .lte("scheduled_at", _now().isoformat())\
        .order("scheduled_at", desc=False)\
        .limit(MAX_SENDS_PER_RUN)\
        .execute()

    logger.info(f"Found {len(due.data)} emails due to send")

    for email in due.data:
        try:
            lead = email.get("leads") or {}
            if not lead.get("email"):
                logger.warning(f"No email for lead in email {email['id']}, cancelling")
                db.table("emails").update({"status": "cancelled"}).eq("id", email["id"]).execute()
                continue

            campaign_res = db.table("campaigns").select("*").eq("id", email["campaign_id"]).execute()
            campaign = campaign_res.data[0] if campaign_res.data else {}
            sequence = get_sequence(campaign)
            cfg = step_config(sequence, email["sequence_step"])

            # For follow-ups: pull step-1's subject + thread_id so we can
            # reply on the same thread.
            previous_body = None
            thread_id = None
            step1_subject = None
            if email["sequence_step"] > 1:
                first = db.table("emails")\
                    .select("subject, body, gmail_thread_id")\
                    .eq("lead_id", email["lead_id"])\
                    .eq("sequence_step", 1)\
                    .eq("status", "sent")\
                    .execute()
                if first.data:
                    step1_subject = first.data[0].get("subject")
                    previous_body = first.data[0].get("body")
                    thread_id = first.data[0].get("gmail_thread_id")

            # Use the already-written body if present (approved step 1),
            # otherwise generate it now (auto follow-ups).
            if email.get("subject") and email.get("body"):
                subject = email["subject"]
                body = email["body"]
            else:
                personalized = personalize_email(
                    lead_name=lead.get("name", ""),
                    lead_title=lead.get("title", ""),
                    lead_company=lead.get("company", ""),
                    sequence_step=email["sequence_step"],
                    previous_email=previous_body,
                )
                subject = personalized["subject"]
                body = personalized["body"]

            # Force same-thread subject on follow-ups. Gmail's API silently
            # opens a new thread if the Subject doesn't match the original.
            if email["sequence_step"] > 1 and step1_subject:
                subject = thread_subject(step1_subject)

            # Resume per step
            resume_filename = None
            if cfg.get("attach_resume") or email.get("attach_resume"):
                resume_filename = campaign.get("resume_filename")

            result = send_email(
                to=lead["email"],
                subject=subject,
                body=body,
                thread_id=thread_id,
                resume_filename=resume_filename,
                email_id=email["id"],          # tracking pixel on follow-ups too
            )

            db.table("emails").update({
                "status": "sent",
                "subject": subject,
                "body": body,
                "sent_at": _now().isoformat(),
                "gmail_message_id": result["gmail_message_id"],
                "gmail_thread_id": result["gmail_thread_id"],
            }).eq("id", email["id"]).execute()

            db.table("leads").update({"status": "contacted"}).eq("id", email["lead_id"]).execute()

            # Schedule the next step from the sequence
            next_step = email["sequence_step"] + 1
            ncfg = step_config(sequence, next_step)
            if ncfg:
                delay = int(ncfg.get("delay_days", 2))
                run_at = _now() + timedelta(days=delay)
                db.table("emails").insert({
                    "lead_id": email["lead_id"],
                    "campaign_id": email["campaign_id"],
                    "status": "pending",
                    "sequence_step": next_step,
                    "scheduled_at": run_at.isoformat(),
                    "attach_resume": bool(ncfg.get("attach_resume", False)),
                }).execute()
                logger.info(f"Scheduled step {next_step} for lead {email['lead_id']} in {delay} days")

            logger.info(f"Sent step {email['sequence_step']} to {lead['email']}")

        except Exception as e:
            logger.error(f"Failed to send email {email['id']}: {e}")
            db.table("emails").update({"status": "failed"}).eq("id", email["id"]).execute()


def start_scheduler():
    scheduler.add_job(
        process_due_emails,
        trigger="interval",
        minutes=15,
        id="process_emails",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Email scheduler started — checking every 15 minutes")


def stop_scheduler():
    scheduler.shutdown()