import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.leads import router as leads_router
from app.routes.campaigns import router as campaigns_router
from app.routes.auth import router as auth_router
from app.routes.resumes import router as resumes_router
from app.routes.tracking import router as tracking_router
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    logger.info("App started — scheduler running")
    yield
    stop_scheduler()
    logger.info("App stopped")


app = FastAPI(
    title="Cold Email Tool",
    description="Lead generation + AI-powered cold email automation",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(campaigns_router)
app.include_router(resumes_router)
app.include_router(tracking_router)


@app.get("/")
async def root():
    return {
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "auth": "/auth/google/login",
            "leads": "/leads/",
            "campaigns": "/campaigns/",
            "resumes": "/resumes/",
            "tracking": "/track/"
        }
    }


@app.get("/health")
async def health():
    return {"status": "ok"}