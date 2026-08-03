from datetime import datetime, timezone
from collections import defaultdict
from fastapi import APIRouter, Depends
from app.db.mongodb import get_db
from app.deps import require_admin
from app.models.common import to_object_id

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def get_dashboard_analytics():
    db = get_db()
    # Total Revenue & Orders (from non-cancelled orders)
    orders = await db.orders.find({"status": {"$ne": "cancelled"}}).to_list(length=10000)
    
    total_revenue = 0.0
    total_orders = len(orders)
    
    # Trackers for aggregation
    product_sales = defaultdict(int)
    category_revenue = defaultdict(float)
    monthly_sales = defaultdict(float)
    
    # Fetch all products to map to category and title efficiently
    products_cache = {}
    
    for order in orders:
        amount = order.get("amount", 0)
        total_revenue += amount
        
        # Monthly trend (YYYY-MM)
        created_at = order.get("created_at")
        if created_at:
            month_key = created_at.strftime("%Y-%m")
            monthly_sales[month_key] += amount
            
        # Items processing
        for item in order.get("items", []):
            pid = item.get("product_id")
            if not pid: continue
            
            qty = item.get("qty", 0)
            price = item.get("price", 0)
            line_total = qty * price
            
            product_sales[pid] += qty
            
            # category logic cache check
            if pid not in products_cache:
                p = await db.products.find_one({"_id": to_object_id(pid)})
                if p:
                    products_cache[pid] = p
            
            p = products_cache.get(pid)
            if p:
                cat_id = p.get("category_id")
                if cat_id:
                    category_revenue[cat_id] += line_total
                    
    # Format top products (Top 10)
    top_products_list = []
    for pid, qty in product_sales.items():
        p = products_cache.get(pid)
        if p:
            top_products_list.append({
                "product_id": pid,
                "title": p.get("title"),
                "qty": qty,
                "image": (p.get("images") or [None])[0]
            })
    top_products_list.sort(key=lambda x: x["qty"], reverse=True)
    
    # Format category revenue (fetch category names)
    cat_rev_list = []
    if category_revenue:
        cat_ids = list(category_revenue.keys())
        categories = await db.categories.find({"_id": {"$in": [to_object_id(cid) for cid in cat_ids]}}).to_list(length=100)
        cat_map = {str(c["_id"]): c.get("name") for c in categories}
        
        for cid, rev in category_revenue.items():
            cat_rev_list.append({
                "category_id": cid,
                "name": cat_map.get(cid, "Unknown"),
                "revenue": rev
            })
    cat_rev_list.sort(key=lambda x: x["revenue"], reverse=True)
    
    # Format monthly sales chronologically
    sales_trend = [{"month": k, "revenue": v} for k, v in monthly_sales.items()]
    sales_trend.sort(key=lambda x: x["month"])
    
    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "top_products": top_products_list[:10],
        "category_revenue": cat_rev_list,
        "sales_trend": sales_trend
    }
