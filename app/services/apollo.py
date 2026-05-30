import httpx
import os
import logging
from dotenv import load_dotenv
from app.models.lead import LeadCreate, SearchParams

load_dotenv()

logger = logging.getLogger(__name__)

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
APOLLO_BASE_URL = "https://api.apollo.io/api/v1"

HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
    "Accept": "application/json",
    "X-Api-Key": APOLLO_API_KEY or ""
}


def score_lead(person: dict, target_companies: list[str] = [], target_titles: list[str] = []) -> int:
    score = 0
    email = person.get("email") or ""
    title = (person.get("title") or "").lower()
    company = (person.get("organization", {}) or {}).get("name", "").lower()
    linkedin = person.get("linkedin_url") or ""

    if email and "@" in email:
        score += 40
    for t in target_titles:
        if t.lower() in title:
            score += 30
            break
    for c in target_companies:
        if c.lower() in company:
            score += 20
            break
    if linkedin:
        score += 10

    return min(score, 100)


def parse_enriched_person(person: dict, target_companies: list[str], target_titles: list[str]) -> LeadCreate:
    org = person.get("organization") or {}
    location_parts = [person.get("city"), person.get("state"), person.get("country")]
    location = ", ".join(p for p in location_parts if p) or None

    return LeadCreate(
        name=person.get("name") or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
        title=person.get("title"),
        company=org.get("name"),
        location=location,
        email=person.get("email"),
        linkedin_url=person.get("linkedin_url"),
        source="apollo",
        score=score_lead(person, target_companies, target_titles)
    )


async def find_organization_ids(company_names: list[str]) -> list[str]:
    org_ids = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for name in company_names:
            payload = {"q_organization_name": name, "per_page": 1, "page": 1}
            response = await client.post(
                f"{APOLLO_BASE_URL}/mixed_companies/search",
                json=payload,
                headers=HEADERS
            )
            logger.info(f"Org search for '{name}': {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Org search failed: {response.text}")
                continue
            data = response.json()
            orgs = data.get("organizations", [])
            if orgs:
                logger.info(f"Found org '{name}' → id={orgs[0]['id']}")
                org_ids.append(orgs[0]["id"])
            else:
                logger.warning(f"No org found for '{name}'")
    return org_ids


async def search_people(params: SearchParams) -> tuple[list[dict], int]:
    if not APOLLO_API_KEY:
        raise ValueError("APOLLO_API_KEY not set in .env")

    payload = {"per_page": params.per_page, "page": params.page}

    if params.titles:
        payload["person_titles"] = params.titles
    if params.locations:
        payload["person_locations"] = params.locations
    if params.seniorities:
        payload["person_seniorities"] = params.seniorities
    if params.employee_ranges:
        payload["organization_num_employees_ranges"] = params.employee_ranges
    if params.keywords:
        payload["q_keywords"] = " ".join(params.keywords)

    if params.company_names:
        org_ids = await find_organization_ids(params.company_names)
        if org_ids:
            payload["organization_ids"] = org_ids
    elif params.company_domains:
        payload["q_organization_domains_list"] = params.company_domains

    logger.info(f"Searching people with payload: {payload}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{APOLLO_BASE_URL}/mixed_people/api_search",
            json=payload,
            headers=HEADERS
        )
        response.raise_for_status()
        data = response.json()

    people = data.get("people", [])
    total = data.get("total_entries", len(people))
    logger.info(f"Search returned {len(people)} people, total={total}")
    return people, total


async def enrich_people(apollo_ids: list[str]) -> list[dict]:
    if not APOLLO_API_KEY:
        raise ValueError("APOLLO_API_KEY not set in .env")

    all_matches = []
    chunks = [apollo_ids[i:i+10] for i in range(0, len(apollo_ids), 10)]

    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in chunks:
            payload = {
                "details": [{"id": aid} for aid in chunk],
                "reveal_personal_emails": False,
                "reveal_phone_number": False
            }
            response = await client.post(
                f"{APOLLO_BASE_URL}/people/bulk_match",
                json=payload,
                headers=HEADERS
            )
            logger.info(f"Bulk enrich status: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Bulk enrich failed: {response.text}")
                continue
            data = response.json()
            logger.info(f"Bulk enrich response keys: {data.keys()}")
            logger.info(f"Credits consumed: {data.get('credits_consumed')}")
            logger.info(f"Unique enriched: {data.get('unique_enriched_records')}")
            logger.info(f"Missing records: {data.get('missing_records')}")
            matches = data.get("matches", [])
            logger.info(f"Matches returned: {len(matches)}")
            all_matches.extend(matches)

    return all_matches


async def search_and_enrich(params: SearchParams) -> tuple[list[LeadCreate], int]:
    raw_people, total = await search_people(params)

    if not raw_people:
        logger.warning("No people returned from search")
        return [], 0

    apollo_ids = [p["id"] for p in raw_people if p.get("id")]
    logger.info(f"Enriching {len(apollo_ids)} people")

    enriched = await enrich_people(apollo_ids)
    logger.info(f"Got {len(enriched)} enriched records")

    leads = [
        parse_enriched_person(p, params.company_names or params.company_domains or [], params.titles or [])
        for p in enriched
        if p
    ]
    logger.info(f"Parsed {len(leads)} leads")

    return leads, total