# import os
# import json
# import base64
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from email.mime.base import MIMEBase
# from email import encoders
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import Flow
# from googleapiclient.discovery import build
# from dotenv import load_dotenv

# load_dotenv()

# SCOPES = [
#     'https://www.googleapis.com/auth/gmail.send',
#     'https://www.googleapis.com/auth/gmail.readonly',
#     'https://www.googleapis.com/auth/gmail.modify'
# ]

# CLIENT_CONFIG = {
#     "web": {
#         "client_id": os.getenv("GMAIL_CLIENT_ID"),
#         "client_secret": os.getenv("GMAIL_CLIENT_SECRET"),
#         "redirect_uris": [os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/google/callback")],
#         "auth_uri": "https://accounts.google.com/o/oauth2/auth",
#         "token_uri": "https://oauth2.googleapis.com/token"
#     }
# }

# TOKEN_FILE = "data/gmail_token.json"
# RESUME_DIR = "data/resumes"
# TRACKING_BASE_URL = os.getenv("TRACKING_BASE_URL", "http://localhost:8000")


# def get_flow() -> Flow:
#     return Flow.from_client_config(
#         CLIENT_CONFIG,
#         scopes=SCOPES,
#         redirect_uri=os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
#     )


# def save_token(credentials: Credentials):
#     os.makedirs("data", exist_ok=True)
#     with open(TOKEN_FILE, "w") as f:
#         json.dump({
#             "token": credentials.token,
#             "refresh_token": credentials.refresh_token,
#             "token_uri": credentials.token_uri,
#             "client_id": credentials.client_id,
#             "client_secret": credentials.client_secret,
#             "scopes": list(credentials.scopes) if credentials.scopes else []
#         }, f)


# def load_token() -> Credentials | None:
#     if not os.path.exists(TOKEN_FILE):
#         return None
#     with open(TOKEN_FILE, "r") as f:
#         data = json.load(f)
#     return Credentials(
#         token=data["token"],
#         refresh_token=data["refresh_token"],
#         token_uri=data["token_uri"],
#         client_id=data["client_id"],
#         client_secret=data["client_secret"],
#         scopes=data["scopes"]
#     )


# def get_gmail_service():
#     creds = load_token()
#     if not creds:
#         raise ValueError("Gmail not connected. Visit /auth/google/login first.")
#     return build("gmail", "v1", credentials=creds)


# def inject_tracking_pixel(html_body: str, email_id: str) -> str:
#     """Inject a 1x1 invisible tracking pixel at the end of the email body."""
#     pixel_url = f"{TRACKING_BASE_URL}/track/open/{email_id}"
#     pixel = f'<img src="{pixel_url}" width="1" height="1" style="display:none" alt="" />'
#     return html_body + pixel


# def build_email(
#     to: str,
#     subject: str,
#     body: str,
#     thread_id: str = None,
#     resume_filename: str = None,
#     email_id: str = None
# ) -> dict:
#     """
#     Build Gmail message with optional resume attachment and open tracking pixel.
#     email_id: used to generate tracking pixel URL
#     """
#     # Convert plain text to HTML
#     html_body = body.replace('\n', '<br>')

#     # Inject tracking pixel if email_id provided
#     if email_id:
#         html_body = inject_tracking_pixel(html_body, email_id)

#     resume_path = None
#     if resume_filename:
#         resume_path = os.path.join(RESUME_DIR, resume_filename)
#         if not os.path.exists(resume_path):
#             resume_path = None

#     if resume_path:
#         message = MIMEMultipart("mixed")
#         message["to"] = to
#         message["subject"] = subject

#         body_part = MIMEMultipart("alternative")
#         body_part.attach(MIMEText(html_body, "html"))
#         message.attach(body_part)

#         with open(resume_path, "rb") as f:
#             pdf = MIMEBase("application", "octet-stream")
#             pdf.set_payload(f.read())
#             encoders.encode_base64(pdf)
#             pdf.add_header(
#                 "Content-Disposition",
#                 "attachment",
#                 filename=resume_filename
#             )
#             message.attach(pdf)
#     else:
#         message = MIMEMultipart("alternative")
#         message["to"] = to
#         message["subject"] = subject
#         message.attach(MIMEText(html_body, "html"))

#     raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
#     payload = {"raw": raw}
#     if thread_id:
#         payload["threadId"] = thread_id
#     return payload


# def send_email(
#     to: str,
#     subject: str,
#     body: str,
#     thread_id: str = None,
#     resume_filename: str = None,
#     email_id: str = None
# ) -> dict:
#     """Send email via Gmail API with tracking pixel and optional resume."""
#     service = get_gmail_service()
#     payload = build_email(to, subject, body, thread_id, resume_filename, email_id)
#     result = service.users().messages().send(userId="me", body=payload).execute()
#     return {
#         "gmail_message_id": result.get("id"),
#         "gmail_thread_id": result.get("threadId")
#     }


# def check_for_replies(thread_id: str) -> bool:
#     """Check if a Gmail thread has more than 1 message."""
#     service = get_gmail_service()
#     thread = service.users().threads().get(userId="me", id=thread_id).execute()
#     messages = thread.get("messages", [])
#     return len(messages) > 1


import os
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from dotenv import load_dotenv
from app.db.database import get_db

load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]

CLIENT_CONFIG = {
    "web": {
        "client_id": os.getenv("GMAIL_CLIENT_ID"),
        "client_secret": os.getenv("GMAIL_CLIENT_SECRET"),
        "redirect_uris": [os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/google/callback")],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token"
    }
}

TRACKING_BASE_URL = os.getenv("TRACKING_BASE_URL", "http://localhost:8000")


def get_flow() -> Flow:
    return Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri=os.getenv("GMAIL_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    )


def save_token(credentials: Credentials):
    """Save Gmail token to Supabase settings table."""
    db = get_db()
    token_data = json.dumps({
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes) if credentials.scopes else []
    })
    db.table("settings").upsert({
        "key": "gmail_token",
        "value": token_data,
        "updated_at": "now()"
    }).execute()


def load_token() -> Credentials | None:
    """Load Gmail token from Supabase settings table."""
    try:
        db = get_db()
        result = db.table("settings").select("value").eq("key", "gmail_token").execute()
        if not result.data:
            return None
        data = json.loads(result.data[0]["value"])
        return Credentials(
            token=data["token"],
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=data["scopes"]
        )
    except Exception:
        return None


def get_gmail_service():
    """Get authenticated Gmail API service."""
    creds = load_token()
    if not creds:
        raise ValueError("Gmail not connected. Visit /auth/google/login first.")
    return build("gmail", "v1", credentials=creds)


def inject_tracking_pixel(html_body: str, email_id: str) -> str:
    """Inject a 1x1 invisible tracking pixel at the end of the email body."""
    pixel_url = f"{TRACKING_BASE_URL}/track/open/{email_id}"
    pixel = f'<img src="{pixel_url}" width="1" height="1" style="display:none" alt="" />'
    return html_body + pixel


def build_email(
    to: str,
    subject: str,
    body: str,
    thread_id: str = None,
    resume_filename: str = None,
    email_id: str = None
) -> dict:
    """Build Gmail message with optional resume from Supabase Storage and tracking pixel."""
    html_body = body.replace('\n', '<br>')

    if email_id:
        html_body = inject_tracking_pixel(html_body, email_id)

    # Download resume from Supabase Storage if provided
    resume_data = None
    if resume_filename:
        try:
            db = get_db()
            resume_data = db.storage.from_("resumes").download(resume_filename)
        except Exception:
            resume_data = None

    if resume_data:
        message = MIMEMultipart("mixed")
        message["to"] = to
        message["subject"] = subject
        body_part = MIMEMultipart("alternative")
        body_part.attach(MIMEText(html_body, "html"))
        message.attach(body_part)
        pdf = MIMEBase("application", "octet-stream")
        pdf.set_payload(resume_data)
        encoders.encode_base64(pdf)
        pdf.add_header("Content-Disposition", "attachment", filename=resume_filename)
        message.attach(pdf)
    else:
        message = MIMEMultipart("alternative")
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    return payload


def send_email(
    to: str,
    subject: str,
    body: str,
    thread_id: str = None,
    resume_filename: str = None,
    email_id: str = None
) -> dict:
    """Send email via Gmail API with tracking pixel and optional resume from Supabase."""
    service = get_gmail_service()
    payload = build_email(to, subject, body, thread_id, resume_filename, email_id)
    result = service.users().messages().send(userId="me", body=payload).execute()
    return {
        "gmail_message_id": result.get("id"),
        "gmail_thread_id": result.get("threadId")
    }


def check_for_replies(thread_id: str) -> bool:
    """Check if a Gmail thread has more than 1 message."""
    service = get_gmail_service()
    thread = service.users().threads().get(userId="me", id=thread_id).execute()
    messages = thread.get("messages", [])
    return len(messages) > 1