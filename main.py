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
from q10_a2a_invoice_agent import (
    router as q10_router,
    install_q10_exception_handlers,
)


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
app.include_router(q10_router)
install_q10_exception_handlers(app)


@app.get("/")
def root():
    import os as _os
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
        "PORT": _os.environ.get("PORT", "(unset)"),
        "AI_API_BASE": "yes" if _os.environ.get("AI_API_BASE", "") else "no",
        "HOSTNAME": _os.environ.get("HOSTNAME", "(unset)"),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }
