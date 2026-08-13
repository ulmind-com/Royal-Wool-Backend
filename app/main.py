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

from app.core.security import decode_access_token
from app.models.common import to_object_id

logger = logging.getLogger("uvicorn.error")

_AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
