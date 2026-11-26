
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.branches import router as branches_router
from app.core.config import settings
from app.api.routes.team import router as team_router
from app.api.routes.products import router as products_router
from app.api.routes.uploads import router as uploads_router
from app.api.routes.historical_imports import router as historical_imports_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.recipes import router as recipes_router
from app.api.routes.stock_movements import router as stock_movements_router
from app.api.routes.analyst_analytics_grants import router as analyst_grants_router
from app.api.routes.staff_operations import router as staff_operations_router


app = FastAPI(
    title="Tavuno API",
    description="AI-powered retail intelligence platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "Tavuno API",
    }


app.include_router(
    auth_router,
    prefix="/api/v1/auth",
)

app.include_router(
    branches_router,
    prefix="/api/v1/branches",
)

app.include_router(
    team_router,
    prefix="/api/v1/team",
)

app.include_router(products_router, prefix="/api/v1/products")
app.include_router(uploads_router, prefix="/api/v1/uploads")
app.include_router(historical_imports_router, prefix="/api/v1/historical-imports")
app.include_router(analytics_router, prefix="/api/v1/analytics")
app.include_router(recipes_router, prefix="/api/v1/recipes")
app.include_router(stock_movements_router, prefix="/api/v1/stock-movements")
app.include_router(analyst_grants_router, prefix="/api/v1/analyst-analytics-grants")
app.include_router(staff_operations_router, prefix="/api/v1/staff-operations")
