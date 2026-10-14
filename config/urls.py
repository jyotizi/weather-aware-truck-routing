from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve

DIST = Path(settings.BASE_DIR) / "frontend" / "dist"


def frontend_index(request):
    if request.path == "/favicon.ico":
        return HttpResponse(status=204)
    index = DIST / "index.html"
    if not index.is_file():
        return HttpResponse(
            "Frontend is not built. From frontend/, run npm install and npm run build. "
            "For development, run the Vite server on port 5173 instead.",
            status=503,
            content_type="text/plain",
        )
    return FileResponse(index.open("rb"))


def frontend_asset(request, path):
    return serve(request, path, document_root=DIST / "assets")


urlpatterns = [
    path("api/", include("planner.urls")),
    re_path(r"^assets/(?P<path>.*)$", frontend_asset),
    re_path(r"^(?!api/).*$", frontend_index),
]
