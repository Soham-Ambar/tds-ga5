from fastapi import FastAPI
from q2_proration import router as proration_router

app = FastAPI()

app.include_router(proration_router)
