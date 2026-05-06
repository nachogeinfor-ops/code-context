"""FastAPI application factory — includes all routers."""

from fastapi import FastAPI

from app.routers import auth, items, users


def create_app() -> FastAPI:
    app = FastAPI(title="Python Repo Fixture API", version="0.1.0")

    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(items.router, prefix="/items", tags=["items"])
    app.include_router(auth.router, prefix="/auth", tags=["auth"])

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
