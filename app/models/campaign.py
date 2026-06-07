from pydantic import BaseModel
from typing import Optional


class SequenceStep(BaseModel):
    step: int
    # Step 1: days from campaign start (usually 0)
    # Step 2+: days AFTER the previous email was sent
    delay_days: int = 0
    attach_resume: bool = False


# Default sequence — matches the usual workflow:
#   Email 1 → sent now,        NO resume
#   Email 2 → 2 days later,    WITH resume
DEFAULT_SEQUENCE = [
    SequenceStep(step=1, delay_days=0, attach_resume=False),
    SequenceStep(step=2, delay_days=2, attach_resume=True),
]


class CampaignCreate(BaseModel):
    name: str
    resume_filename: Optional[str] = None
    sequence: Optional[list[SequenceStep]] = None  # None → DEFAULT_SEQUENCE