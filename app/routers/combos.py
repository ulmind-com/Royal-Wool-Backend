from fastapi import APIRouter, Depends, HTTPException
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.combo import ComboIn
from app.models.common import serialize, to_object_id

router = APIRouter(prefix="/combos", tags=["combos"])

@router.get("")
async def list_combos():
    db = get_db()
    docs = await db.combos.find().sort("name", 1).to_list(100)
    return [serialize(d) for d in docs]

@router.post("", dependencies=[Depends(require_admin)])
async def create_combo(body: ComboIn):
    db = get_db()
    res = await db.combos.insert_one(body.model_dump())
    doc = await db.combos.find_one({"_id": res.inserted_id})
    return serialize(doc)

@router.put("/{cid}", dependencies=[Depends(require_admin)])
async def update_combo(cid: str, body: ComboIn):
    db = get_db()
    res = await db.combos.find_one_and_update(
        {"_id": to_object_id(cid)},
        {"$set": body.model_dump()},
        return_document=True
    )
    if not res:
        raise HTTPException(404, "Combo not found")
    return serialize(res)

@router.delete("/{cid}", dependencies=[Depends(require_admin)])
async def delete_combo(cid: str):
    db = get_db()
    res = await db.combos.delete_one({"_id": to_object_id(cid)})
    if res.deleted_count == 0:
        raise HTTPException(404, "Combo not found")
    return {"ok": True}
