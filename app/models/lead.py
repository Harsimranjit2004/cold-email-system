from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class LeadStatus(str, Enum):
    new = "new"
    contacted = "contacted"
    replied = "replied"
    follow_up = "follow-up"
    rejected = "rejected"


class LeadBase(BaseModel):
    name: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    linkedin_url: Optional[str] = None
    source: Optional[str] = "apollo"
    notes: Optional[str] = None


class LeadCreate(LeadBase):
    score: Optional[int] = 0


class LeadUpdate(BaseModel):
    status: Optional[LeadStatus] = None
    notes: Optional[str] = None
    score: Optional[int] = None


class Lead(LeadBase):
    id: str
    score: int = 0
    status: LeadStatus = LeadStatus.new

    class Config:
        from_attributes = True


class SearchParams(BaseModel):
    titles: Optional[list[str]] = Field(
        default=None,
        description="Job titles e.g. ['Engineering Manager', 'CTO']"
    )
    keywords: Optional[list[str]] = Field(
        default=None,
        description="Free text keywords"
    )
    company_names: Optional[list[str]] = Field(
        default=None,
        description="Company names e.g. ['Shopify', 'Wealthsimple'] — searched by name"
    )
    company_domains: Optional[list[str]] = Field(
        default=None,
        description="Company domains e.g. ['shopify.com'] — used if company_names not provided"
    )
    locations: Optional[list[str]] = Field(
        default=["Toronto, Canada"],
        description="Person locations"
    )
    seniorities: Optional[list[str]] = Field(
        default=None,
        description="owner, founder, c_suite, vp, head, director, manager, senior, entry, intern"
    )
    employee_ranges: Optional[list[str]] = Field(
        default=None,
        description="Headcount ranges e.g. ['10,50', '50,200']"
    )
    per_page: int = Field(default=10, ge=1, le=100)
    page: int = Field(default=1, ge=1)


class SearchResponse(BaseModel):
    total: int
    leads: list[Lead]
    page: int
    per_page: int