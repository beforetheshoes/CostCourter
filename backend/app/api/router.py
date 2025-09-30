from __future__ import annotations

from fastapi import APIRouter

from .endpoints import (
    admin,
    auth,
    backups,
    health,
    notifications,
    price_history,
    pricing,
    product_urls,
    products,
    search,
    stores,
    tags,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(backups.router, prefix="/backups", tags=["backups"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(stores.router, prefix="/stores", tags=["stores"])
api_router.include_router(tags.router, prefix="/tags", tags=["tags"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(
    product_urls.router, prefix="/product-urls", tags=["product-urls"]
)
api_router.include_router(
    price_history.router, prefix="/price-history", tags=["price-history"]
)
api_router.include_router(pricing.router, prefix="/pricing", tags=["pricing"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
