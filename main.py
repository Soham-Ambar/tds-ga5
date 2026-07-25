from fastapi import FastAPI

from q2_proration import router as proration_router
from q3_guardrail import router as guardrail_router
from q4_skill_scanner import router as skill_scanner_router
from q5_run_control import router as run_control_router
from q6_mcp_server import router as mcp_router


app = FastAPI(
    title="TDS GA5 API",
    version="1.0.0",
)


app.include_router(proration_router)
app.include_router(guardrail_router)
app.include_router(skill_scanner_router)
app.include_router(run_control_router)
app.include_router(mcp_router)


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
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
    }
