import math
from datetime import datetime

from app.models.settings import Settings

_KEY = {"_id": "config"}


async def get_settings(db) -> Settings:
    doc = await db.settings.find_one(_KEY)
    if not doc:
        return Settings()
    doc.pop("_id", None)
    return Settings(**doc)


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def cod_availability(settings: Settings, user: dict | None = None) -> dict:
    """Whether Cash on Delivery can be used right now for this user.

    Combines the three admin controls: the global switch, an optional
    scheduled pause window, and a per-user block. Returns
    {available: bool, reason: str} — `reason` is customer-facing.
    """
    cod = settings.cod
    if not cod.enabled:
        return {"available": False, "reason": "Cash on Delivery is currently unavailable."}

    now = datetime.now()
    frm, until = _parse_dt(cod.disabled_from), _parse_dt(cod.disabled_until)
    paused = (frm or until) and (frm is None or now >= frm) and (until is None or now <= until)
    if paused:
        return {"available": False, "reason": "Cash on Delivery is temporarily paused. Please pay online."}

    if user and user.get("cod_blocked"):
        return {"available": False, "reason": "Cash on Delivery isn't available for your account."}

    return {"available": True, "reason": ""}


async def save_settings(db, settings: Settings) -> Settings:
    await db.settings.update_one(_KEY, {"$set": settings.model_dump()}, upsert=True)
    return settings


def coupon_discount(coupon: dict, subtotal: float) -> float:
    """Compute the discount a coupon gives on a subtotal (respecting min/cap)."""
    if not coupon:
        return 0.0
    if subtotal < coupon.get("min_order", 0):
        return 0.0
    if coupon.get("type") == "flat":
        return round(min(coupon.get("value", 0), subtotal), 2)
    # percent
    disc = subtotal * coupon.get("value", 0) / 100
    cap = coupon.get("max_discount", 0)
    if cap and cap > 0:
        disc = min(disc, cap)
    return round(disc, 2)


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _apply(mrp: float, price: float, disc: float, on: str) -> tuple:
    """(final, struck, off_pct) after applying an admin discount."""
    if disc and disc > 0:
        base = mrp if on == "mrp" and mrp else price
        final = round(base * (1 - disc / 100), 2)
    else:
        final = price
    struck = mrp if mrp and mrp > final else None
    off = round((struck - final) / struck * 100) if struck else 0
    return final, struck, off


def product_final_price(product: dict) -> dict:
    """Base display pricing (product-level mrp/price + admin discount)."""
    final, struck, off = _apply(
        product.get("mrp") or 0, product.get("price") or 0,
        product.get("discount_pct") or 0, product.get("discount_on") or "price",
    )
    return {"final_price": final, "struck_price": struck, "off_pct": off}


def _variant_params(product: dict, color=None, dye_lot=None) -> tuple:
    """Resolve (price, mrp, discount_pct, discount_on) for a colour+dye_lot.
    Fallback order for every field: dye_lot -> colour -> product base."""
    price = product.get("price") or 0
    mrp = product.get("mrp") or 0
    disc = product.get("discount_pct") or 0
    on = product.get("discount_on") or "price"
    for c in (product.get("colors") or []):
        if isinstance(c, dict) and c.get("name") == color:
            if c.get("price") is not None:
                price = c["price"]
            if c.get("mrp") is not None:
                mrp = c["mrp"]
            if c.get("discount_pct") is not None:
                disc = c["discount_pct"]
            if c.get("discount_on"):
                on = c["discount_on"]
            for dl in (c.get("dye_lots") or []):
                if dl.get("dye_lot") == dye_lot:
                    if dl.get("price") is not None:
                        price = dl["price"]
                    if dl.get("mrp") is not None:
                        mrp = dl["mrp"]
                    if dl.get("discount_pct") is not None:
                        disc = dl["discount_pct"]
                    if dl.get("discount_on"):
                        on = dl["discount_on"]
                    break
            break
    return price, mrp, disc, on


def resolve_price(product: dict, color=None, dye_lot=None) -> dict:
    """Display pricing for a specific colour + dye_lot selection."""
    price, mrp, disc, on = _variant_params(product, color, dye_lot)
    final, struck, off = _apply(mrp, price, disc, on)
    return {"final_price": final, "struck_price": struck, "off_pct": off}


def _combos(product: dict) -> list[tuple]:
    """(final, struck, off) for every colour+dye_lot combination."""
    out = []
    colors = [c for c in (product.get("colors") or []) if isinstance(c, dict)]
    if colors:
        for c in colors:
            dye_lots = c.get("dye_lots") or []
            targets = [dl.get("dye_lot") for dl in dye_lots] if dye_lots else [None]
            for dl in targets:
                p, m, d, o = _variant_params(product, c.get("name"), dl)
                out.append(_apply(m, p, d, o))
    else:
        p, m, d, o = _variant_params(product, None, None)
        out.append(_apply(m, p, d, o))
    return out or [_apply(product.get("mrp") or 0, product.get("price") or 0,
                          product.get("discount_pct") or 0, product.get("discount_on") or "price")]


def price_span(product: dict) -> dict:
    """Card pricing: cheapest combo as the representative, plus the price range."""
    combos = _combos(product)
    finals = [c[0] for c in combos]
    lo, hi = min(finals), max(finals)
    rep = min(combos, key=lambda c: c[0])  # cheapest combo drives the shown price
    return {
        "final_price": rep[0],
        "struck_price": rep[1],
        "off_pct": rep[2],
        "price_from": lo,
        "price_to": hi,
        "price_varies": round(lo, 2) != round(hi, 2),
    }


def variant_stock(product: dict, color=None, dye_lot=None) -> int:
    for c in (product.get("colors") or []):
        if isinstance(c, dict) and c.get("name") == color:
            dye_lots = c.get("dye_lots") or []
            if dye_lots:
                for dl in dye_lots:
                    if dl.get("dye_lot") == dye_lot:
                        return int(dl.get("stock", 0))
                return 0
            return int(c.get("stock", 0))
    return int(product.get("stock", 0))


def total_stock(product: dict) -> int:
    colors = [c for c in (product.get("colors") or []) if isinstance(c, dict)]
    if colors:
        s = 0
        for c in colors:
            dye_lots = c.get("dye_lots") or []
            s += sum(int(x.get("stock", 0)) for x in dye_lots) if dye_lots else int(c.get("stock", 0))
        return s
    return int(product.get("stock", 0))


def compute_delivery(settings: Settings, subtotal: float, dest_state: str, total_weight_grams: float) -> dict:
    """Return {fee, distance_km, deliverable, free}.
    Computes Pan-India weight-based delivery fees relying on state.
    """
    d = settings.delivery
    weight_kg = total_weight_grams / 1000.0 if total_weight_grams else 0

    if d.free_above and subtotal >= d.free_above:
        return {"fee": 0.0, "distance_km": None, "deliverable": True, "free": True}

    is_home = False
    if dest_state and d.home_state and dest_state.strip().lower() == d.home_state.strip().lower():
        is_home = True

    if is_home:
        base_fee = d.home_base_fee
        base_weight = d.home_base_weight_kg
        extra_fee = d.home_extra_fee_per_kg
    else:
        base_fee = d.rest_base_fee
        base_weight = d.rest_base_weight_kg
        extra_fee = d.rest_extra_fee_per_kg

    fee = base_fee
    if weight_kg > base_weight:
        # Couriers usually charge for every additional full or partial kg.
        # math.ceil handles partial kg as a full unit.
        extra_kg = math.ceil(weight_kg - base_weight)
        fee += extra_kg * extra_fee

    return {"fee": round(fee, 2), "distance_km": None, "deliverable": True, "free": fee == 0}
