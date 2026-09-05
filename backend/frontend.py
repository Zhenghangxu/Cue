"""Serve exported pages, with media directory URLs falling back to the library."""

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                return response
        except HTTPException as exc:
            if exc.status_code != 404:
                raise

        # Never return HTML for missing API routes or Next.js assets.
        first = path.strip("/").split("/", 1)[0]
        headers = dict(scope.get("headers", []))
        if first in {"api", "_next"} or b"text/html" not in headers.get(b"accept", b""):
            raise HTTPException(status_code=404)
        shell = f"{first}/index.html" if first in {"en", "zh"} else "index.html"
        return await super().get_response(shell, scope)
