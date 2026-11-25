
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.branches import router as branches_router
from app.core.config import settings
from app.api.routes.team import router as team_router


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
