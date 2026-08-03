from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.models.common import serialize, to_object_id
from app.models.waitlist import WaitlistCreate

router = APIRouter(prefix="/waitlist", tags=["waitlist"])


@router.post("")
async def join_waitlist(body: WaitlistCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    # Check if product exists
    prod = await db.products.find_one({"_id": to_object_id(body.product_id)})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    # Check if already requested
    existing = await db.waitlist.find_one({
        "user_id": user["id"],
        "product_id": body.product_id,
        "status": "pending"
    })
    
    if existing:
        return {"success": True, "message": "Already on waitlist"}

    doc = {
        "user_id": user["id"],
        "product_id": body.product_id,
        "color_name": body.color_name,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    res = await db.waitlist.insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


@router.get("/admin/summary", dependencies=[Depends(require_admin)])
async def waitlist_summary():
    db = get_db()
    waitlists = await db.waitlist.find({"status": "pending"}).to_list(length=5000)
    
    if not waitlists:
        return []

    grouped = defaultdict(int)
    for w in waitlists:
        grouped[w["product_id"]] += 1

    product_ids = list(grouped.keys())
    products = await db.products.find({"_id": {"$in": [to_object_id(pid) for pid in product_ids]}}).to_list(length=1000)

    result = []
    for p in products:
        p_id = str(p["_id"])
        result.append({
            "product": serialize(p),
            "count": grouped[p_id]
        })
        
    return sorted(result, key=lambda x: x["count"], reverse=True)


@router.post("/admin/{product_id}/resolve", dependencies=[Depends(require_admin)])
async def resolve_waitlist(product_id: str):
    db = get_db()
    res = await db.waitlist.update_many(
        {"product_id": product_id, "status": "pending"},
        {"$set": {"status": "notified", "updated_at": datetime.now(timezone.utc)}}
    )
    return {"success": True, "resolved_count": res.modified_count}
