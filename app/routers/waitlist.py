from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.models.common import serialize, to_object_id
from app.models.waitlist import WaitlistCreate
from app.services.pricing import price_span, total_stock

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
    """Admin: which products are out of stock and who is waiting for each,
    oldest request first so the admin can see who has waited the longest.
    """
    db = get_db()
    # Oldest-first, so each product's grouped list is already in queue order.
    waitlists = await db.waitlist.find({"status": "pending"}).sort("created_at", 1).to_list(length=5000)

    if not waitlists:
        return []

    grouped: dict[str, list[dict]] = defaultdict(list)
    for w in waitlists:
        grouped[w["product_id"]].append(w)

    product_ids = list(grouped.keys())
    products = await db.products.find({"_id": {"$in": [to_object_id(pid) for pid in product_ids]}}).to_list(length=1000)

    user_ids = {w["user_id"] for w in waitlists if w.get("user_id")}
    users: dict[str, dict] = {}
    if user_ids:
        object_ids = []
        for uid in user_ids:
            try:
                object_ids.append(to_object_id(uid))
            except Exception:
                continue
        if object_ids:
            async for u in db.users.find({"_id": {"$in": object_ids}}, {"name": 1, "email": 1, "phone": 1}):
                users[str(u["_id"])] = u

    result = []
    for p in products:
        p_id = str(p["_id"])
        d = serialize(p)
        d.update(price_span(d))  # final_price etc. — same computed fields the product list uses
        d["total_stock"] = total_stock(d)

        entries = grouped[p_id]
        waiting = []
        for w in entries:
            u = users.get(w.get("user_id"), {})
            waiting.append({
                "user_id": w.get("user_id"),
                "name": u.get("name") or "Unknown customer",
                "email": u.get("email") or "",
                "phone": u.get("phone") or "",
                "color_name": w.get("color_name"),
                "waiting_since": w.get("created_at"),
            })

        result.append({
            "product": d,
            "count": len(entries),
            "waiting": waiting,
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
