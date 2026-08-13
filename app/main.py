import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.mongodb import close_mongo_connection, connect_to_mongo, get_db
from app.routers import (
    admins,
    analytics,
    auth,
    banners,
    blog,
    brands,
    categories,
    chat,
    combos,
    coupons,
    google_reviews,
    home_sections,
    orders,
    products,
    product_lines,
    certifications,
    countries,
    recommendations,
    reviews,
    search,
    settings as settings_router,
    site_media,
    upload,
    users,
    waitlist,
    wishlist,
)
from app.services.google_business import GoogleBusinessNotConfigured, sync_reviews

SWEEP_SECONDS = 60
GOOGLE_SYNC_SECONDS = 6 * 60 * 60  # pull new Google reviews four times a day


async def _google_review_sync():
    """Keep the storefront's Google reviews in step with the Business Profile."""
    while True:
        try:
            result = await sync_reviews(get_db())
            print(f"[google-reviews] synced: {result}")
        except GoogleBusinessNotConfigured:
            pass  # credentials not set up yet — stay quiet
        except Exception as e:  # pragma: no cover
            print(f"[google-reviews] sync error: {e}")
        await asyncio.sleep(GOOGLE_SYNC_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    google_sync = asyncio.create_task(_google_review_sync())
    yield
    google_sync.cancel()
    await close_mongo_connection()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
import logging
from datetime import datetime, timezone
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.security import decode_access_token
from app.models.common import to_object_id

logger = logging.getLogger("uvicorn.error")

_AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# First URL path segment -> the section key(s) that grant write access to it.
# A non-super admin may only mutate an endpoint if their permissions include at
# least one granting section. Segments not listed here are always allowed
# (uploads, search, wishlist, analytics reads, /admins is already super-only…).
_SECTION_WRITE = {
    "products": {"products"},
    "product-lines": {"products"},
    "brands": {"products"},
    "certifications": {"products"},
    "countries": {"products"},
    "categories": {"categories"},
    "combos": {"combos"},
    "waitlist": {"waitlist"},
    "orders": {"orders"},
    "reviews": {"reviews"},
    "coupons": {"coupons"},
    "users": {"users"},
    "home-sections": {"home-layout"},
    "banners": {"home-layout"},
    "site-media": {"home-layout"},
    "blog": {"blog"},
    "settings": {"settings", "announcements"},  # Store Settings + Store Marquee
}


async def _permission_denied(request: Request) -> bool:
    """True if a non-super admin is writing to a section they don't have access to."""
    if request.method not in _AUDITED_METHODS:
        return False
    segment = request.url.path.strip("/").split("/")[0]
    grantors = _SECTION_WRITE.get(segment)
    if not grantors:
        return False
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False  # unauthenticated -> let the route's own auth reject it
    try:
        payload = decode_access_token(auth_header.split(" ", 1)[1])
    except Exception:
        return False
    if payload.get("role") != "admin":
        return False
    admin = await get_db().users.find_one({"_id": to_object_id(payload.get("sub"))})
    if not admin or admin.get("is_super", True):
        return False  # owner / super admin -> unrestricted
    perms = admin.get("permissions")
    if perms is None:
        return False  # legacy admin without a permission list -> unrestricted
    return grantors.isdisjoint(perms)


async def _record_admin_action(request: Request, status_code: int) -> None:
    """Log any mutating request made by an admin so a super admin can audit it."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return
    try:
        payload = decode_access_token(auth_header.split(" ", 1)[1])
    except Exception:
        return
    if payload.get("role") != "admin":
        return
    db = get_db()
    admin = await db.users.find_one({"_id": to_object_id(payload.get("sub"))})
    if not admin:
        return
    await db.admin_activity.insert_one({
        "admin_id": str(admin["_id"]),
        "admin_email": admin.get("email"),
        "admin_name": admin.get("name"),
        "method": request.method,
        "path": request.url.path,
        "status": status_code,
        "at": datetime.now(timezone.utc),
    })


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()

    try:
        if await _permission_denied(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "You don't have access to this section."},
            )
    except Exception:
        pass  # never let the permission check itself break a request

    response = await call_next(request)
    process_time = time.time() - start_time

    # Don't clutter logs with static files or health checks if you prefer
    if not request.url.path.startswith("/static"):
        logger.info(f"🌐 [{request.method}] {request.url.path} - Status: {response.status_code} - {process_time * 1000:.1f}ms")

    if request.method in _AUDITED_METHODS:
        try:
            await _record_admin_action(request, response.status_code)
        except Exception:
            pass  # auditing must never break the actual request

    return response

app.include_router(auth.router)
app.include_router(admins.router)
app.include_router(analytics.router)
app.include_router(brands.router)
app.include_router(categories.router)
app.include_router(combos.router)
app.include_router(coupons.router)
app.include_router(certifications.router)
app.include_router(countries.router)
app.include_router(orders.router)
app.include_router(products.router)
app.include_router(product_lines.router)
app.include_router(recommendations.router)
app.include_router(wishlist.router)
app.include_router(reviews.router)
app.include_router(banners.router)
app.include_router(blog.router)
app.include_router(settings_router.router)
app.include_router(users.router)
app.include_router(upload.router)
app.include_router(search.router)
app.include_router(recommendations.router)
app.include_router(home_sections.router)
app.include_router(chat.router)
app.include_router(site_media.router)
app.include_router(waitlist.router)
app.include_router(google_reviews.router)


import os

from fastapi.responses import FileResponse


@app.get("/", tags=["health"])
async def health():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.ENV}
