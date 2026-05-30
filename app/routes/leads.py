import csv
import io
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models.lead import SearchParams, SearchResponse, LeadUpdate, Lead
from app.services.apollo import search_and_enrich
from app.db.database import get_db

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("/search", response_model=SearchResponse)
async def search_leads(params: SearchParams):
    """
    Search Apollo for leads and save to Supabase.
    Step 1 (free): search by title/location/company
    Step 2 (credits): enrich to get emails and full names
    """
    try:
        leads, total = await search_and_enrich(params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Apollo error: {str(e)}")

    if not leads:
        return SearchResponse(total=0, leads=[], page=params.page, per_page=params.per_page)

    db = get_db()
    saved_leads = []

    for lead in leads:
        lead_data = lead.model_dump()

        # Skip leads with no email and no name
        if not lead_data.get("name") or lead_data["name"].strip() == "":
            continue

        try:
            # Upsert by email to avoid duplicates (if no email, insert anyway)
            if lead_data.get("email"):
                existing = db.table("leads").select("id").eq("email", lead_data["email"]).execute()
                if existing.data:
                    # Already exists, skip
                    saved_leads.append({**lead_data, "id": existing.data[0]["id"], "status": "new"})
                    continue

            result = db.table("leads").insert(lead_data).execute()
            if result.data:
                saved_leads.append(result.data[0])

        except Exception:
            # If insert fails (e.g. duplicate), skip silently
            continue

    return SearchResponse(
        total=total,
        leads=[Lead(**l) for l in saved_leads],
        page=params.page,
        per_page=params.per_page
    )


@router.get("/", response_model=list[Lead])
async def get_leads(status: str = None, limit: int = 100, offset: int = 0):
    """Get all saved leads, optionally filtered by status."""
    db = get_db()
    query = db.table("leads").select("*").range(offset, offset + limit - 1)

    if status:
        query = query.eq("status", status)

    result = query.order("score", desc=True).execute()
    return [Lead(**l) for l in result.data]


@router.patch("/{lead_id}", response_model=Lead)
async def update_lead(lead_id: str, update: LeadUpdate):
    """Update lead status or notes."""
    db = get_db()
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = db.table("leads").update(update_data).eq("id", lead_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    return Lead(**result.data[0])


@router.get("/export/csv")
async def export_csv(status: str = None):
    """Export leads to CSV file."""
    db = get_db()
    query = db.table("leads").select("*")

    if status:
        query = query.eq("status", status)

    result = query.order("score", desc=True).execute()
    leads = result.data

    if not leads:
        raise HTTPException(status_code=404, detail="No leads found")

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "score", "name", "title", "company", "location",
        "email", "linkedin_url", "source", "status", "notes"
    ])
    writer.writeheader()

    for lead in leads:
        writer.writerow({
            "score": lead.get("score", 0),
            "name": lead.get("name", ""),
            "title": lead.get("title", ""),
            "company": lead.get("company", ""),
            "location": lead.get("location", ""),
            "email": lead.get("email", ""),
            "linkedin_url": lead.get("linkedin_url", ""),
            "source": lead.get("source", ""),
            "status": lead.get("status", "new"),
            "notes": lead.get("notes", ""),
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"}
    )


@router.delete("/{lead_id}")
async def delete_lead(lead_id: str):
    """Delete a lead."""
    db = get_db()
    result = db.table("leads").delete().eq("id", lead_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Lead not found")

    return {"message": "Lead deleted"}