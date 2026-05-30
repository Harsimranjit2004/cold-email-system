import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.db.database import get_db
from app.services.gmail import send_email, check_for_replies
from app.services.ai import personalize_email

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

FOLLOW_UP_DAYS = {
    1: 3,   # Send follow-up 1 after 3 days
    2: 7,   # Send follow-up 2 after 7 days
}


async def process_due_emails():
    """
    Runs every hour.
    1. Check for replies on sent emails — stop sequence if replied
    2. Send any emails that are scheduled and due
    """
    logger.info("Scheduler: checking due emails...")
    db = get_db()

    # Step 1: Check for replies on active threads
    sent_emails = db.table("emails")\
        .select("*")\
        .eq("status", "sent")\
        .not_.is_("gmail_thread_id", "null")\
        .execute()

    for email in sent_emails.data:
        try:
            has_reply = check_for_replies(email["gmail_thread_id"])
            if has_reply:
                logger.info(f"Reply detected for lead {email['lead_id']}")
                # Mark email as replied
                db.table("emails")\
                    .update({"status": "replied", "replied_at": datetime.utcnow().isoformat()})\
                    .eq("id", email["id"])\
                    .execute()
                # Update lead status
                db.table("leads")\
                    .update({"status": "replied"})\
                    .eq("id", email["lead_id"])\
                    .execute()
                # Cancel any pending follow-ups for this lead
                db.table("emails")\
                    .update({"status": "cancelled"})\
                    .eq("lead_id", email["lead_id"])\
                    .eq("status", "pending")\
                    .execute()
        except Exception as e:
            logger.error(f"Reply check failed for email {email['id']}: {e}")

    # Step 2: Send due emails
    now = datetime.utcnow().isoformat()
    due_emails = db.table("emails")\
        .select("*, leads(*)")\
        .eq("status", "pending")\
        .lte("scheduled_at", now)\
        .execute()

    logger.info(f"Found {len(due_emails.data)} emails due to send")

    for email in due_emails.data:
        try:
            lead = email.get("leads", {})
            if not lead or not lead.get("email"):
                logger.warning(f"No email for lead in email {email['id']}, skipping")
                db.table("emails").update({"status": "cancelled"}).eq("id", email["id"]).execute()
                continue

            # Get previous email body for follow-ups
            previous_body = None
            if email["sequence_step"] > 1:
                prev = db.table("emails")\
                    .select("body")\
                    .eq("lead_id", email["lead_id"])\
                    .eq("sequence_step", email["sequence_step"] - 1)\
                    .eq("status", "sent")\
                    .execute()
                if prev.data:
                    previous_body = prev.data[0]["body"]

            # Get thread ID from first email for reply threading
            thread_id = None
            if email["sequence_step"] > 1:
                first = db.table("emails")\
                    .select("gmail_thread_id")\
                    .eq("lead_id", email["lead_id"])\
                    .eq("sequence_step", 1)\
                    .execute()
                if first.data:
                    thread_id = first.data[0].get("gmail_thread_id")

            # AI personalize
            personalized = personalize_email(
                lead_name=lead.get("name", ""),
                lead_title=lead.get("title", ""),
                lead_company=lead.get("company", ""),
                sequence_step=email["sequence_step"],
                previous_email=previous_body
            )

            # Send via Gmail
            result = send_email(
                to=lead["email"],
                subject=personalized["subject"],
                body=personalized["body"],
                thread_id=thread_id
            )

            # Update email record
            db.table("emails").update({
                "status": "sent",
                "subject": personalized["subject"],
                "body": personalized["body"],
                "sent_at": datetime.utcnow().isoformat(),
                "gmail_message_id": result["gmail_message_id"],
                "gmail_thread_id": result["gmail_thread_id"]
            }).eq("id", email["id"]).execute()

            # Update lead status
            db.table("leads")\
                .update({"status": "contacted"})\
                .eq("id", email["lead_id"])\
                .execute()

            # Schedule next follow-up if applicable
            next_step = email["sequence_step"] + 1
            if next_step in FOLLOW_UP_DAYS:
                days = FOLLOW_UP_DAYS[next_step]
                scheduled_at = (datetime.utcnow() + timedelta(days=days)).isoformat()
                db.table("emails").insert({
                    "lead_id": email["lead_id"],
                    "campaign_id": email["campaign_id"],
                    "status": "pending",
                    "sequence_step": next_step,
                    "scheduled_at": scheduled_at
                }).execute()
                logger.info(f"Scheduled step {next_step} for lead {email['lead_id']} in {days} days")

            logger.info(f"Sent step {email['sequence_step']} to {lead['email']}")

        except Exception as e:
            logger.error(f"Failed to send email {email['id']}: {e}")
            db.table("emails")\
                .update({"status": "failed"})\
                .eq("id", email["id"])\
                .execute()


def start_scheduler():
    """Start the background scheduler."""
    scheduler.add_job(
        process_due_emails,
        trigger="interval",
        minutes=30,
        id="process_emails",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Email scheduler started — checking every 60 minutes")


def stop_scheduler():
    scheduler.shutdown()