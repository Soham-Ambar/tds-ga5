from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ProrationRequest(BaseModel):
    old_price: float
    new_price: float
    days_remaining: float
    days_in_actual_month: float
    spec: str


class ProrationResponse(BaseModel):
    charge: float


@router.post("/proration", response_model=ProrationResponse)
def calculate_proration(req: ProrationRequest):
    difference = req.new_price - req.old_price

    if req.spec == "v1":
        divisor = 30
    elif req.spec == "v2":
        divisor = req.days_in_actual_month
    else:
        divisor = 30

    charge = difference * (req.days_remaining / divisor)

    return ProrationResponse(charge=round(charge, 2))
