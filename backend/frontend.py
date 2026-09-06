"""Serve exported pages, with media directory URLs falling back to the library."""

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        # StaticFiles.get_path uses native separators; route matching uses '/'.
        path = path.replace("\\", "/")
        try:
            response = await super().get_response(path, scope)
            if response.status_code != 404:
                if path.strip("/") in {"sw.js", "manifest.webmanifest", "offline.html"}:
                    response.headers["Cache-Control"] = "no-cache"
                if path.strip("/") == "sw.js":
                    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
                    response.headers["Service-Worker-Allowed"] = "/"
                elif path.strip("/") == "manifest.webmanifest":
                    response.headers["Content-Type"] = "application/manifest+json"
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
