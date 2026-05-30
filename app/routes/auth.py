import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app.services.gmail import get_flow, save_token, load_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Store flow between login and callback
_flow = None


@router.get("/google/login")
async def google_login():
    """Redirect to Google OAuth consent screen."""
    global _flow
    _flow = get_flow()
    auth_url, _ = _flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    return RedirectResponse(auth_url)


@router.get("/google/callback")
async def google_callback(code: str, state: str = None):
    """Exchange auth code for token and save it."""
    global _flow
    try:
        if not _flow:
            _flow = get_flow()
        _flow.fetch_token(code=code)
        credentials = _flow.credentials
        save_token(credentials)
        _flow = None
        logger.info("Gmail connected successfully")
        return {"message": "Gmail connected successfully. You can now send emails."}
    except Exception as e:
        logger.error(f"Gmail auth failed: {e}")
        raise HTTPException(status_code=400, detail=f"Auth failed: {str(e)}")


@router.get("/google/status")
async def google_status():
    """Check if Gmail is connected."""
    creds = load_token()
    if not creds:
        return {"connected": False, "message": "Visit /auth/google/login to connect Gmail"}
    return {"connected": True, "message": "Gmail is connected and ready"}


@router.delete("/google/disconnect")
async def google_disconnect():
    """Disconnect Gmail by deleting saved token."""
    import os
    token_file = "data/gmail_token.json"
    if os.path.exists(token_file):
        os.remove(token_file)
    return {"message": "Gmail disconnected"}