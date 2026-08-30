"""Cache policy for Vite's content-addressed frontend assets."""

from fastapi import Request


IMMUTABLE_ASSET_CACHE = "public, max-age=31536000, immutable"


def install_static_cache(app) -> None:
    """Cache successful hashed assets without changing document responses."""

    @app.middleware("http")
    async def static_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/") and response.status_code < 400:
            response.headers["Cache-Control"] = IMMUTABLE_ASSET_CACHE
        return response
