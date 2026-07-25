from fastapi import FastAPI

from q2_proration import router as proration_router
from q3_guardrail import router as guardrail_router
from q4_skill_scanner import router as skill_scanner_router
from q5_run_control import router as run_control_router
from q6_mcp_server import router as mcp_router
from q8_redteam_guardrail import (
    router as redteam_guardrail_router,
    create_required_files,
)
from q9_mailroom import router as mailroom_router


app = FastAPI(
    title="TDS GA5 API",
    version="1.0.0",
)


@app.on_event("startup")
def seed_redteam_files() -> None:
    try:
        create_required_files()
    except (PermissionError, FileNotFoundError, OSError):
        pass


app.include_router(proration_router)
app.include_router(guardrail_router)
app.include_router(skill_scanner_router)
app.include_router(run_control_router)
app.include_router(mcp_router)
app.include_router(redteam_guardrail_router)
app.include_router(mailroom_router)


@app.get("/")
def root():
    return {
        "message": "TDS GA5 API is running",
        "endpoints": [
            "POST /proration",
            "POST /guardrail",
            "POST /skill-scan",
            "POST /run-control",
            "POST /mcp",
            "POST /redteam-guardrail",
            "POST /mailroom-agent",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }
