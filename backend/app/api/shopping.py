from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.db.models import FoodItem, InventoryItem, ShoppingPlan
from app.db.session import get_db
from app.schemas.inventory import (
    InventoryEntryResponse,
    InventoryTextRequest,
    InventoryTextResponse,
    InventoryUpdate,
    ShoppingItemQuantityUpdate,
)
from app.services.inventory import (
    add_purchased_items,
    food_for_inventory_item,
    format_inventory_quantity,
    serialize_inventory_item,
)
from app.services.inventory_ingestion import (
    InventoryExtractionError,
    process_inventory_text,
)
from app.services.shopping import (
    delete_shopping_item,
    generate_weekly_shopping_plan,
    update_shopping_item_quantity,
)

router = APIRouter(tags=["shopping"])


def serialize_plan(plan: ShoppingPlan, settings: Settings) -> dict[str, Any]:
    minimum = (
        settings.coop_online_minimum_chf
        if plan.retailer == "Coop"
        else settings.migros_online_minimum_chf
    )
    online_total = sum(
        float(item.get("estimated_chf", 0))
        for item in plan.items_json
        if item.get("purchase_mode") == "online"
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
) -> dict[str, Any]:
    plan = db.scalar(select(ShoppingPlan).where(ShoppingPlan.id == plan_id).with_for_update())
    if plan is None:
        raise HTTPException(status_code=404, detail="Shopping plan not found")
    if plan.status != "purchased":
        try:
            updated_ids = add_purchased_items(db, plan.items_json)
            plan.status = "purchased"
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return {"status": plan.status, "inventory_items_updated": len(updated_ids)}
    return {"status": plan.status, "inventory_items_updated": 0}


@router.patch("/shopping/{plan_id}/items/{item_index}")
def update_shopping_item(
    plan_id: UUID,
    item_index: int,
    payload: ShoppingItemQuantityUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    plan = db.get(ShoppingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Shopping plan not found")
    try:
        update_shopping_item_quantity(plan, item_index, payload.quantity, payload.unit)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    db.refresh(plan)
    return serialize_plan(plan, settings)


@router.delete("/shopping/{plan_id}/items/{item_index}", status_code=status.HTTP_204_NO_CONTENT)
def remove_shopping_item(
    plan_id: UUID,
    item_index: int,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Response:
    plan = db.get(ShoppingPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Shopping plan not found")
    try:
        delete_shopping_item(plan, item_index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/inventory", response_model=list[InventoryEntryResponse])
def get_inventory(
    _: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[InventoryEntryResponse]:
    rows = db.execute(
        select(InventoryItem, FoodItem)
        .outerjoin(FoodItem, FoodItem.id == InventoryItem.food_item_id)
        .order_by(func.lower(func.coalesce(FoodItem.name, InventoryItem.custom_name)))
    ).all()
    return [
        InventoryEntryResponse.model_validate(serialize_inventory_item(item, food))
        for item, food in rows
    ]


@router.post("/inventory/from-text", response_model=InventoryTextResponse)
def add_inventory_from_text(
    payload: InventoryTextRequest,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InventoryTextResponse:
    try:
        return process_inventory_text(db, settings, payload.text)
    except RuntimeError as exc:
        if str(exc) == "OPENAI_API_KEY is not configured":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Inventory parsing requires an OpenAI API key. Nothing was changed.",
            ) from exc
        if isinstance(exc, InventoryExtractionError):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        raise


@router.patch("/inventory/{item_id}")
def update_inventory(
    item_id: UUID,
    payload: InventoryUpdate,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> InventoryEntryResponse:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    changes = payload.model_dump(exclude_unset=True)
    name = changes.pop("name", None)
    if name is not None:
        if item.food_item_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Catalog ingredient names cannot be changed.",
            )
        item.custom_name = name
    for field, value in changes.items():
        setattr(item, field, value)
    if {"quantity_estimate", "unit"} & changes.keys():
        item.quantity_label = (
            format_inventory_quantity(item.quantity_estimate, item.unit)
            if item.quantity_estimate is not None
            else None
        )
    db.commit()
    db.refresh(item)
    return InventoryEntryResponse.model_validate(
        serialize_inventory_item(item, food_for_inventory_item(db, item))
    )


@router.delete("/inventory/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory(
    item_id: UUID,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
