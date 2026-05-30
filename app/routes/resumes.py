import logging
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from app.db.database import get_db
import io

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resumes", tags=["resumes"])

BUCKET = "resumes"


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Upload a resume PDF to Supabase Storage."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")

    contents = await file.read()
    db = get_db()

    try:
        db.storage.from_(BUCKET).upload(
            path=file.filename,
            file=contents,
            file_options={"content-type": "application/pdf", "upsert": "true"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    logger.info(f"Resume uploaded to Supabase Storage: {file.filename}")
    return {
        "message": "Resume uploaded successfully",
        "filename": file.filename,
        "size_kb": round(len(contents) / 1024, 1)
    }


@router.get("/")
async def list_resumes():
    """List all uploaded resumes from Supabase Storage."""
    db = get_db()
    try:
        result = db.storage.from_(BUCKET).list()
        files = []
        for f in result:
            name = f.get("name", "")
            if not name.endswith(".pdf"):
                continue
            metadata = f.get("metadata") or {}
            size = metadata.get("size", 0) or 0
            files.append({
                "filename": name,
                "size_kb": round(size / 1024, 1)
            })
        return files
    except Exception as e:
        logger.error(f"Failed to list resumes: {e}")
        return []


@router.delete("/{filename}")
async def delete_resume(filename: str):
    """Delete a resume from Supabase Storage."""
    db = get_db()
    try:
        db.storage.from_(BUCKET).remove([filename])
        return {"message": f"{filename} deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")


@router.get("/download/{filename}")
async def download_resume(filename: str):
    """Download a resume from Supabase Storage."""
    db = get_db()
    try:
        data = db.storage.from_(BUCKET).download(filename)
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@router.get("/url/{filename}")
async def get_resume_url(filename: str):
    """Get a signed URL for a resume (valid for 1 hour)."""
    db = get_db()
    try:
        result = db.storage.from_(BUCKET).create_signed_url(filename, 3600)
        return {"url": result["signedURL"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get URL: {str(e)}")