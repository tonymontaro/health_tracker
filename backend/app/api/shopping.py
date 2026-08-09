from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import FoodItem, InventoryItem, ShoppingPlan
from app.db.session import get_db
from app.schemas.api import InventoryUpdate
from app.services.inventory import add_purchased_items
from app.services.shopping import generate_weekly_shopping_plan

router = APIRouter(tags=["shopping"])


def serialize_plan(plan: ShoppingPlan, settings: Settings) -> dict[str, Any]:
    minimum = (
        settings.coop_online_minimum_chf
        if plan.retailer == "Coop"
        else settings.migros_online_minimum_chf
    )
    online_total = sum(
        item["estimated_chf"] for item in plan.items_json if item["purchase_mode"] == "online"
    )
    return {
        "id": str(plan.id),
        "week_start": plan.week_start.isoformat(),
        "retailer": plan.retailer,
        "mode": plan.mode,
        "estimated_total_chf": plan.estimated_total_chf,
        "online_total_chf": online_total,
        "online_minimum_chf": minimum,
        "online_minimum_met": online_total >= minimum,
        "items": plan.items_json,
        "status": plan.status,
    }


@router.get("/shopping/current")
def get_current_shopping(
    retailer: Literal["Coop", "Migros"] = "Coop",
    _: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    today = datetime.now(ZoneInfo(settings.app_timezone)).date()
    week_start = today - timedelta(days=today.weekday())
    plan = generate_weekly_shopping_plan(db, settings, week_start, retailer)
    return serialize_plan(plan, settings)


@router.post("/shopping/{plan_id}/mark-purchased")
def mark_purchased(
    plan_id: UUID,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    plan = db.get(ShoppingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Shopping plan not found")
    if plan.status != "purchased":
        add_purchased_items(db, plan.items_json)
        plan.status = "purchased"
        db.commit()
    return {"status": plan.status}


@router.get("/inventory")
def get_inventory(
    _: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(InventoryItem, FoodItem)
        .join(FoodItem, FoodItem.id == InventoryItem.food_item_id)
        .order_by(FoodItem.name)
    ).all()
    return [
        {
            "id": str(item.id),
            "food": food.name,
            "quantity_estimate": item.quantity_estimate,
            "quantity_label": item.quantity_label,
            "unit": item.unit,
            "confidence": item.confidence,
            "expires_on": item.expires_on.isoformat() if item.expires_on else None,
            "location": item.location,
        }
        for item, food in rows
    ]


@router.patch("/inventory/{item_id}")
def update_inventory(
    item_id: UUID,
    payload: InventoryUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return {"id": str(item.id), "status": "updated"}
