import re
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.core.config import settings as app_settings
from app.db.mongodb import get_db
from app.deps import get_current_user, require_admin
from app.models.common import serialize, to_object_id
from app.models.order import OrderCreate, OrderVerify, BulkStatusUpdate
from app.routers.coupons import get_coupon
from app.services import razorpay_service
from app.services.pricing import (
    compute_delivery,
    coupon_discount,
    get_settings,
    resolve_price,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _resolve_item_image(prod: dict, color_name: str | None) -> str | None:
    """Return the best image for a specific colour variant.

    Priority: colour variant images[0] → swatch_image → product images[0].
    Falls back to the product's default hero image when the colour has no
    dedicated images or when no colour was selected.
    """
    if color_name:
        for c in prod.get("colors") or []:
            if isinstance(c, dict) and c.get("name") == color_name:
                if c.get("images"):
                    return c["images"][0]
                if c.get("swatch_image"):
                    return c["swatch_image"]
                break
    return (prod.get("images") or [None])[0]


def _matched_colour_image(prod: dict, color_name: str | None) -> str | None:
    """Only returns an image when `color_name` matches a colour on `prod`
    and that colour now has a photo of its own. Tries an exact name match
    first, then — only when that fails — a prefix match (case/space
    insensitive), because the admin has been known to rename a colour after
    orders were placed against it (e.g. "Azure Blue" -> "Azure Blue
    ShadeOLV033"), which breaks an exact match for no reason a customer
    would understand. The prefix match is only trusted when it identifies
    exactly one colour; if the old name could plausibly mean more than one
    of today's colours, this returns None rather than guess.

    Never falls back to the product's generic image — this is used to
    retroactively refresh what an already-placed order displays, so it must
    never downgrade a stored image that may already be correct.
    """
    if not color_name:
        return None
    colours = [c for c in (prod.get("colors") or []) if isinstance(c, dict)]

    def _image_of(c: dict) -> str | None:
        if c.get("images"):
            return c["images"][0]
        if c.get("swatch_image"):
            return c["swatch_image"]
        return None

    for c in colours:
        if c.get("name") == color_name:
            return _image_of(c)

    needle = color_name.strip().lower()
    if not needle:
        return None
    candidates = [c for c in colours if (c.get("name") or "").strip().lower().startswith(needle)]
    if len(candidates) == 1:
        return _image_of(candidates[0])
    return None


def _refresh_item_images(cache: dict, items: list[dict] | None) -> None:
    """Point each order item's image at its colour's CURRENT photo when one
    now exists. Only mutates the in-memory dict being sent in a response or
    rendered into a PDF/email — the stored order document is never written
    back, so this is safe to call on every read.
    """
    for it in items or []:
        prod = cache.get(it.get("product_id"))
        if not prod:
            continue
        fresh = _matched_colour_image(prod, it.get("color"))
        if fresh:
            it["image"] = fresh


async def _product_image_cache(db, order_docs: list[dict]) -> dict[str, dict]:
    """Batch-fetch every product referenced by a set of orders, keyed by id
    string, so refreshing images for a whole order list costs one query."""
    ids = {
        it["product_id"]
        for d in order_docs
        for it in (d.get("items") or [])
        if it.get("product_id")
    }
    object_ids = []
    for pid in ids:
        try:
            object_ids.append(to_object_id(pid))
        except Exception:
            continue
    cache: dict[str, dict] = {}
    if object_ids:
        async for p in db.products.find({"_id": {"$in": object_ids}}):
            cache[str(p["_id"])] = p
    return cache


STAGES = ["placed", "confirmed", "shipped", "out_for_delivery", "delivered"]

STATUS_MSG = {
    "confirmed": "Your order is confirmed and being packed 📦",
    "shipped": "Your order has been shipped 🚚",
    "out_for_delivery": "Your order is out for delivery 🛵",
    "delivered": "Your order has been delivered ✅",
    "cancelled": "Your order was cancelled",
}


async def _build_bill(db, items_in, address, coupon, user_id=None):
    settings = await get_settings(db)
    order_items = []
    lines = []  # (line_total, {cgst, sgst, igst})
    subtotal = 0.0
    total_weight_grams = 0.0
    cart_state = []

    for it in items_in:
        prod = await db.products.find_one({"_id": to_object_id(it.product_id)})
        if not prod or not prod.get("is_active", True):
            raise HTTPException(status_code=400, detail="Product unavailable")
        # Price for the exact colour the customer chose (variant-aware).
        unit = resolve_price(prod, it.color)["final_price"]
        line_total = unit * it.qty
        subtotal += line_total
        total_weight_grams += float(prod.get("shipping_weight") or 0) * it.qty
        comp = {
            "cgst": float(prod.get("cgst") or 0),
            "sgst": float(prod.get("sgst") or 0),
            "igst": float(prod.get("igst") or 0),
        }
        # A product with no GST of its own falls back to the store-wide rate from
        # Settings (tax_rate is a fraction, e.g. 0.05 -> 5%): half CGST + half
        # SGST within the state, the full rate as IGST outside it.
        if not any(comp.values()):
            store_rate = float(settings.tax_rate or 0) * 100
            comp = {
                "cgst": store_rate / 2,
                "sgst": store_rate / 2,
                "igst": store_rate,
            }
        
        cart_state.append({
            "product_id": it.product_id,
            "unit": unit,
            "qty": it.qty,
            "it": it,
            "prod": prod,
            "comp": comp,
            "unbundled_qty": it.qty,
            "line_total": line_total
        })

    combo_discount = 0.0
    now = datetime.now(timezone.utc)
    combos = await db.combos.find({"active": True}).to_list(100)
    for combo in combos:
        # Time validity check
        start_date = combo.get("start_date")
        if start_date and start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if start_date and now < start_date:
            continue
            
        end_date = combo.get("end_date")
        if end_date and end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        if end_date and now > end_date:
            continue

        available_units = []
        for state in cart_state:
            is_eligible = False
            if str(state["product_id"]) in combo.get("product_ids", []):
                is_eligible = True
            elif combo.get("weight_target") is not None:
                try:
                    if state["prod"].get("skein_weight") is not None and float(state["prod"]["skein_weight"]) == float(combo["weight_target"]):
                        is_eligible = True
                except (ValueError, TypeError):
                    pass
            
            if is_eligible and state["unbundled_qty"] > 0:
                available_units.extend([(state["unit"], state)] * state["unbundled_qty"])
                    
        available_units.sort(key=lambda x: x[0], reverse=True)
        num_bundles = len(available_units) // combo.get("qty", 1)
        
        if num_bundles > 0:
            items_to_bundle = num_bundles * combo["qty"]
            regular_price_of_bundled = sum(u[0] for u in available_units[:items_to_bundle])
            bundle_price_total = num_bundles * combo["price"]
            
            discount_for_this_combo = regular_price_of_bundled - bundle_price_total
            if discount_for_this_combo > 0:
                combo_discount += discount_for_this_combo
                
                # Deduct these units from unbundled_qty
                sorted_state = sorted(cart_state, key=lambda x: x["unit"], reverse=True)
                units_to_remove = items_to_bundle
                for state in sorted_state:
                    is_eligible = False
                    if str(state["product_id"]) in combo.get("product_ids", []):
                        is_eligible = True
                    elif combo.get("weight_target") is not None:
                        try:
                            if state["prod"].get("skein_weight") is not None and float(state["prod"]["skein_weight"]) == float(combo["weight_target"]):
                                is_eligible = True
                        except (ValueError, TypeError):
                            pass
                    
                    if is_eligible:
                        take = min(state["unbundled_qty"], units_to_remove)
                        state["unbundled_qty"] -= take
                        units_to_remove -= take
                        if units_to_remove == 0:
                            break

    for state in cart_state:
        lines.append((state["line_total"], state["comp"]))
        order_items.append(
            {
                "product_id": state["it"].product_id,
                "title": state["prod"]["title"],
                "price": state["unit"],
                "qty": state["it"].qty,
                "color": state["it"].color,
                "size": state["it"].size,
                "cgst": state["comp"]["cgst"],
                "sgst": state["comp"]["sgst"],
                "igst": state["comp"]["igst"],
                "image": _resolve_item_image(state["prod"], state["it"].color),
            }
        )

    coupon_doc = await get_coupon(db, coupon, user_id)
    # The coupon discount is calculated on the subtotal.
    # The final discount is coupon_discount + combo_discount
    discount = (coupon_discount(coupon_doc, subtotal) if coupon_doc else 0.0) + combo_discount

    dest_state = getattr(address, "state", "") or ""
    deliv = compute_delivery(settings, subtotal - discount, dest_state, total_weight_grams)

    free_reason = "threshold" if deliv["free"] else None
    if coupon_doc and coupon_doc.get("free_shipping"):
        deliv["fee"] = 0.0
        deliv["free"] = True
        free_reason = "coupon"

    # Same-state order -> CGST + SGST from the product; different state -> IGST.
    shop_state = (settings.shop.state or "").strip().lower()
    dest_state_lower = dest_state.strip().lower()
    interstate = bool(shop_state and dest_state_lower and shop_state != dest_state_lower)

    total_cgst = total_sgst = total_igst = 0.0
    tax_items = []
    for oi, (line_total, comp) in zip(order_items, lines):
        share = (line_total / subtotal * discount) if subtotal else 0.0
        taxable = max(0.0, line_total - share)
        if interstate:
            i_cgst = i_sgst = 0.0
            i_igst = round(taxable * comp["igst"] / 100, 2)
        else:
            i_cgst = round(taxable * comp["cgst"] / 100, 2)
            i_sgst = round(taxable * comp["sgst"] / 100, 2)
            i_igst = 0.0
        total_cgst += i_cgst
        total_sgst += i_sgst
        total_igst += i_igst
        rate = comp["igst"] if interstate else (comp["cgst"] + comp["sgst"])
        tax_items.append({
            "title": oi["title"], "qty": oi["qty"], "rate": rate,
            "cgst": i_cgst, "sgst": i_sgst, "igst": i_igst,
            "taxable": round(taxable, 2), "tax": round(i_cgst + i_sgst + i_igst, 2),
        })
    total_cgst = round(total_cgst, 2)
    total_sgst = round(total_sgst, 2)
    total_igst = round(total_igst, 2)
    total_tax = round(total_cgst + total_sgst + total_igst, 2)

    gst = {
        "total": total_tax,
        "interstate": interstate,
        "cgst": total_cgst,
        "sgst": total_sgst,
        "igst": total_igst,
        "items": tax_items,  # per-product GST breakdown
    }

    total = round((subtotal - discount) + deliv["fee"] + total_tax, 2)

    bill = {
        "subtotal": round(subtotal, 2),
        "discount": discount,
        "delivery": deliv["fee"],
        "delivery_free": deliv["free"],
        "delivery_free_reason": free_reason,
        "distance_km": deliv["distance_km"],
        "deliverable": deliv["deliverable"],
        "tax": total_tax,
        "gst": gst,
        "total": total,
        "currency": settings.currency,          # display symbol (₹)
        "currency_code": settings.currency_code,  # ISO code for Razorpay (INR)
        "coupon_applied": discount > 0,
    }
    return order_items, bill


@router.post("/quote")
async def quote(body: OrderCreate, user: dict = Depends(get_current_user)):
    """Preview the bill (delivery/tax/total) before placing the order."""
    db = get_db()
    _, bill = await _build_bill(db, body.items, body.address, body.coupon_code, user["id"])
    return bill


async def _decrement_stock(db, order_items):
    for it in order_items:
        prod = await db.products.find_one({"_id": to_object_id(it["product_id"])})
        if not prod:
            continue
        colors = prod.get("colors") or []
        if colors and it.get("color"):
            for c in colors:
                if c.get("name") == it["color"]:
                    sizes = c.get("sizes") or []
                    if sizes and it.get("size"):
                        for ss in sizes:
                            if ss.get("size") == it["size"]:
                                ss["stock"] = max(0, int(ss.get("stock", 0)) - it["qty"])
                    else:
                        c["stock"] = max(0, int(c.get("stock", 0)) - it["qty"])
            await db.products.update_one({"_id": prod["_id"]}, {"$set": {"colors": colors}})
        else:
            await db.products.update_one({"_id": prod["_id"]}, {"$inc": {"stock": -it["qty"]}})


async def _restore_stock(db, order_items):
    """Put stock back (inverse of _decrement_stock) — used on cancellation."""
    for it in order_items:
        prod = await db.products.find_one({"_id": to_object_id(it["product_id"])})
        if not prod:
            continue
        colors = prod.get("colors") or []
        if colors and it.get("color"):
            for c in colors:
                if c.get("name") == it["color"]:
                    sizes = c.get("sizes") or []
                    if sizes and it.get("size"):
                        for ss in sizes:
                            if ss.get("size") == it["size"]:
                                ss["stock"] = int(ss.get("stock", 0)) + it["qty"]
                    else:
                        c["stock"] = int(c.get("stock", 0)) + it["qty"]
            await db.products.update_one({"_id": prod["_id"]}, {"$set": {"colors": colors}})
        else:
            await db.products.update_one({"_id": prod["_id"]}, {"$inc": {"stock": it["qty"]}})


@router.post("")
async def create_order(body: OrderCreate, user: dict = Depends(get_current_user)):
    db = get_db()
    order_items, bill = await _build_bill(db, body.items, body.address, body.coupon_code, user["id"])
    if not bill["deliverable"]:
        raise HTTPException(status_code=400, detail="Address is outside the delivery area")
    if bill["subtotal"] <= 0:
        raise HTTPException(status_code=400, detail="Empty order")

    doc = {
        "user_id": user["id"],
        "items": order_items,
        "address": body.address.model_dump(),
        "payment_method": "online",
        "coupon_code": body.coupon_code,
        **bill,
        "amount": bill["total"],
        "status": "pending_payment",
        "razorpay_order_id": None,
        "razorpay_payment_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    res = await db.orders.insert_one(doc)
    our_id = str(res.inserted_id)

    try:
        rp = razorpay_service.create_order(
            round(bill["total"] * 100), receipt=our_id, currency=bill.get("currency_code", "INR")
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    await db.orders.update_one({"_id": res.inserted_id}, {"$set": {"razorpay_order_id": rp["id"]}})

    return {
        "order_id": our_id,
        "payment_method": "online",
        "razorpay_order_id": rp["id"],
        "amount": round(bill["total"] * 100),
        "currency": bill.get("currency_code", "INR"),  # ISO code for Razorpay
        "key_id": app_settings.RAZORPAY_KEY_ID,
        "bill": bill,
        "prefill": {
            "name": body.address.name or user.get("name", ""),
            "contact": body.address.phone,
            "email": user.get("email", ""),
        },
    }


@router.post("/verify")
async def verify_order(body: OrderVerify, user: dict = Depends(get_current_user)):
    db = get_db()
    order = await db.orders.find_one({"_id": to_object_id(body.order_id)})
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found")

    ok = razorpay_service.verify_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    )
    if not ok:
        await db.orders.update_one({"_id": order["_id"]}, {"$set": {"status": "cancelled"}})
        raise HTTPException(status_code=400, detail="Payment verification failed")

    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"status": "placed", "razorpay_payment_id": body.razorpay_payment_id,
                  "paid_at": datetime.now(timezone.utc)}},
    )
    await _decrement_stock(db, order["items"])
    if order.get("coupon_code"):
        await db.coupons.update_one({"code": order["coupon_code"].strip().upper()}, {"$inc": {"used_count": 1}})

    # Send invoice email with PDF attachment (non-blocking — don't fail the response)
    try:
        from app.services.email_service import send_invoice_email
        from app.services.invoice_template import render_pdf
        from io import BytesIO
        from xhtml2pdf import pisa

        # Re-fetch the order to get the updated fields (status, payment_id, paid_at)
        updated_order = await db.orders.find_one({"_id": order["_id"]})
        if updated_order:
            cache = await _product_image_cache(db, [updated_order])
            _refresh_item_images(cache, updated_order.get("items"))
            user_doc = await db.users.find_one({"_id": to_object_id(user["id"])})
            email = user_doc.get("email", "") if user_doc else ""
            if email:
                # Generate PDF bytes for attachment
                pdf_bytes = None
                try:
                    html_str = render_pdf(updated_order)
                    buf = BytesIO()
                    pisa.CreatePDF(html_str, dest=buf)
                    pdf_bytes = buf.getvalue()
                except Exception as pe:
                    print(f"[invoice-pdf] generation failed: {pe}")
                send_invoice_email(email, updated_order, pdf_bytes)
    except Exception as e:
        print(f"[invoice-email] failed to send: {e}")

    return {"status": "confirmed", "order_id": body.order_id}





def _fmt_window(hours: float) -> str:
    if hours >= 24 and hours % 24 == 0:
        d = int(hours // 24)
        return f"{d} day" + ("s" if d != 1 else "")
    h = int(hours) if float(hours).is_integer() else hours
    return f"{h} hour" + ("s" if h != 1 else "")


@router.get("")
async def my_orders(user: dict = Depends(get_current_user)):
    db = get_db()
    # Hide abandoned online orders that were never paid — any online order
    # without a razorpay_payment_id is a ghost order (old or new).
    _no_ghosts = {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}
    docs = await db.orders.find({
        "user_id": user["id"],
        **_no_ghosts,
    }).sort("created_at", -1).to_list(length=100)
    cache = await _product_image_cache(db, docs)
    out = [serialize(d) for d in docs]
    for o in out:
        _refresh_item_images(cache, o.get("items"))
    return out


@router.get("/admin/status-counts", dependencies=[Depends(require_admin)])
async def admin_status_counts():
    db = get_db()
    pipeline = [
        {"$match": {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    results = await db.orders.aggregate(pipeline).to_list(length=None)
    counts = {r["_id"]: r["count"] for r in results}
    all_stages = STAGES + ["cancelled"]
    return {s: counts.get(s, 0) for s in all_stages}


@router.get("/admin/all", dependencies=[Depends(require_admin)])
async def all_orders(
    status: str | None = None,
    q: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    user_id: str | None = None,
    limit: int = 100
):
    db = get_db()
    # Exclude ghost orders: online orders where payment was never completed.
    query: dict = {"$nor": [{"payment_method": "online", "razorpay_payment_id": None}]}
    
    if user_id:
        query["user_id"] = user_id

    if status:
        query["status"] = status
        
    if q:
        q = q.strip()
        search_val = q.lstrip("#")
        query["$or"] = [
            {"address.name": {"$regex": re.escape(search_val), "$options": "i"}},
            {"address.phone": {"$regex": re.escape(search_val), "$options": "i"}},
            {"$expr": {"$regexMatch": {"input": {"$toString": "$_id"}, "regex": re.escape(search_val), "options": "i"}}}
        ]
            
    if start_date or end_date:
        query["created_at"] = {}
        if start_date:
            try:
                dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                query["created_at"]["$gte"] = dt
            except ValueError:
                pass
        if end_date:
            try:
                dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                query["created_at"]["$lte"] = dt
            except ValueError:
                pass
        if not query["created_at"]:
            del query["created_at"]

    docs = await db.orders.find(query).sort("created_at", -1).to_list(length=limit)
    cache = await _product_image_cache(db, docs)
    out = [serialize(d) for d in docs]
    for o in out:
        _refresh_item_images(cache, o.get("items"))
    return out


@router.get("/admin/refunds", dependencies=[Depends(require_admin)])
async def admin_refunds():
    """All cancelled orders with their refund details (newest cancellation first)."""
    db = get_db()
    docs = await db.orders.find({"status": "cancelled"}).sort("cancelled_at", -1).to_list(length=500)
    return [serialize(d) for d in docs]


@router.post("/{order_id}/refund", dependencies=[Depends(require_admin)])
async def admin_refund(order_id: str):
    """Manually initiate / retry a Razorpay refund for a paid online order."""
    db = get_db()
    order = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_method") != "online" or not order.get("razorpay_payment_id"):
        raise HTTPException(status_code=400, detail="This order has no online payment to refund")
    if order.get("refund_status") == "initiated":
        raise HTTPException(status_code=400, detail="A refund is already initiated for this order")
    try:
        r = razorpay_service.refund(order["razorpay_payment_id"], int(round(order["amount"] * 100)))
    except Exception as e:
        await db.orders.update_one({"_id": order["_id"]}, {"$set": {"refund_status": "failed"}})
        raise HTTPException(status_code=502, detail=f"Refund failed: {e}")
    await db.orders.update_one(
        {"_id": order["_id"]}, {"$set": {"refund_id": r.get("id"), "refund_status": "initiated"}}
    )
    return {"refund_status": "initiated", "refund_id": r.get("id")}


@router.get("/{order_id}/payment", dependencies=[Depends(require_admin)])
async def admin_order_payment(order_id: str):
    """Live payment record from Razorpay for an online order — method, bank,
    UPI VPA / card, gateway fee, contact. The stored txn/coupon fields already
    come back with the order; this pulls the rest straight from the gateway."""
    db = get_db()
    order = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    pid = order.get("razorpay_payment_id")
    if not pid:
        raise HTTPException(status_code=400, detail="This order has no online payment")
    try:
        p = razorpay_service.fetch_payment(pid)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch payment: {e}")
    card = p.get("card") or {}
    return {
        "id": p.get("id"),
        "status": p.get("status"),
        "captured": p.get("captured"),
        "method": p.get("method"),
        "amount": (p.get("amount") or 0) / 100,
        "currency": p.get("currency"),
        "bank": p.get("bank"),
        "wallet": p.get("wallet"),
        "vpa": p.get("vpa"),
        "card_last4": card.get("last4"),
        "card_network": card.get("network"),
        "card_type": card.get("type"),
        "email": p.get("email"),
        "contact": p.get("contact"),
        "fee": (p.get("fee") or 0) / 100,
        "tax": (p.get("tax") or 0) / 100,
        "created_at": p.get("created_at"),  # unix seconds
        "acquirer_data": p.get("acquirer_data"),
    }


@router.get("/{order_id}/invoice")
async def order_invoice(order_id: str, user: dict = Depends(get_current_user)):
    """Generate a premium PDF invoice for the customer to download."""
    db = get_db()
    doc = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not doc or (doc["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=404, detail="Order not found")

    cache = await _product_image_cache(db, [doc])
    _refresh_item_images(cache, doc.get("items"))

    from app.services.invoice_template import render_pdf
    from io import BytesIO
    from xhtml2pdf import pisa
    from fastapi.responses import StreamingResponse

    html_str = render_pdf(doc)
    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html_str, dest=pdf_buffer)

    if pisa_status.err:
        # Fallback: return HTML if PDF generation fails
        return HTMLResponse(content=html_str)

    pdf_buffer.seek(0)
    short_id = str(doc["_id"])[-8:].upper()
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Invoice_Royal_Wool_{short_id}.pdf"'
        },
    )


@router.get("/{order_id}")
async def get_order(order_id: str, user: dict = Depends(get_current_user)):
    db = get_db()
    doc = await db.orders.find_one({"_id": to_object_id(order_id)})
    if not doc or (doc["user_id"] != user["id"] and user.get("role") != "admin"):
        raise HTTPException(status_code=404, detail="Order not found")
    cache = await _product_image_cache(db, [doc])
    out = serialize(doc)
    _refresh_item_images(cache, out.get("items"))
    return out


@router.patch("/{order_id}/status", dependencies=[Depends(require_admin)])
async def update_status(
    order_id: str, 
    status: str = Body(..., embed=True),
    tracking_id: str | None = Body(None, embed=True),
    tracking_url: str | None = Body(None, embed=True)
):
    if status not in STAGES + ["cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    db = get_db()
    
    update_data = {"status": status}
    if tracking_id:
        update_data["tracking_id"] = tracking_id
    if tracking_url:
        update_data["tracking_url"] = tracking_url

    res = await db.orders.find_one_and_update(
        {"_id": to_object_id(order_id)}, {"$set": update_data}, return_document=True
    )
    if not res:
        raise HTTPException(status_code=404, detail="Order not found")

    # Count units sold once, and stamp the delivery time (drives the return
    # window), when the order is delivered.
    if status == "delivered" and not res.get("sold_counted"):
        for it in res.get("items", []):
            await db.products.update_one(
                {"_id": to_object_id(it["product_id"])}, {"$inc": {"sold_count": it["qty"]}}
            )
        await db.orders.update_one(
            {"_id": res["_id"]},
            {"$set": {"sold_counted": True, "delivered_at": datetime.now(timezone.utc)}},
        )

    return serialize(res)


@router.patch("/admin/bulk-status", dependencies=[Depends(require_admin)])
async def bulk_update_status(body: BulkStatusUpdate):
    if body.status not in STAGES + ["cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    db = get_db()
    obj_ids = [to_object_id(id) for id in body.order_ids]
    
    # We fetch the orders first to see if they were already delivered
    orders = await db.orders.find({"_id": {"$in": obj_ids}}).to_list(length=None)
    
    # Perform the bulk update for the status field
    await db.orders.update_many(
        {"_id": {"$in": obj_ids}}, 
        {"$set": {"status": body.status}}
    )
    
    # If the new status is delivered, we must handle sold_count
    if body.status == "delivered":
        for o in orders:
            if not o.get("sold_counted"):
                for it in o.get("items", []):
                    await db.products.update_one(
                        {"_id": to_object_id(it["product_id"])}, {"$inc": {"sold_count": it["qty"]}}
                    )
                await db.orders.update_one(
                    {"_id": o["_id"]},
                    {"$set": {"sold_counted": True, "delivered_at": datetime.now(timezone.utc)}},
                )

    return {"modified_count": len(orders), "status": body.status}
