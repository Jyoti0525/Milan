"""The HTTP surface.

Thin on purpose. Every decision worth making has already been made in the
engine, and an API that starts making its own is a second implementation of
the same rules that will disagree with the first one eventually.

Money crosses this boundary as integer paise, never as a formatted string and
never as a float. Formatting is a display concern and belongs in the browser;
floats would reintroduce, at the last possible moment, exactly the
imprecision the whole engine is built to avoid.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from milan.api.service import (
    ImportRef,
    ImportView,
    RunNotFoundError,
    RunRef,
    RunView,
    Service,
)
from milan.persistence.store import StaleDatasetError

DEV_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
"""The Next.js dev server on its usual port, and nothing else.

Narrow because this API serves a merchant's settlement data. It is a local
tool today, and the version of this that ships with `allow_origins=["*"]`
because it was convenient during a hackathon is the version that stays that
way.

`next dev` steps to another port when 3000 is taken, which is exactly the
moment the temptation to widen this appears. `MILAN_WEB_ORIGIN` is the answer
instead: a deliberate, per-machine addition rather than a permanent hole.
"""

ORIGIN_ENV = "MILAN_WEB_ORIGIN"


def allowed_origins() -> list[str]:
    """The dev origins, plus anything the environment explicitly names.

    Comma-separated, so a developer whose dev server landed on 3002 can say
    so without editing the source and without opening it to everything.
    """
    extra = os.environ.get(ORIGIN_ENV, "")
    named = [origin.strip().rstrip("/") for origin in extra.split(",") if origin.strip()]
    return [*DEV_ORIGINS, *named]


def create_app(root: Path | None = None) -> FastAPI:
    service = Service(root)
    app = FastAPI(
        title="Milan",
        summary="Settlement reconciliation that proves where every rupee went.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "data_root": str(service.root)}

    @app.get("/api/runs")
    def runs() -> list[RunRef]:
        """Every run on disk. Empty is a normal answer, not an error - it
        means nothing has been generated yet, and the UI says so."""
        return list(service.runs())

    @app.get("/api/runs/{difficulty}/{seed}")
    def run(difficulty: str, seed: int) -> RunView:
        try:
            return service.view(difficulty, seed)
        except RunNotFoundError as missing:
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except StaleDatasetError as stale:
            # 409, not 500. Nothing has gone wrong with the server; the data
            # on disk is from a different version of the generator, and the
            # message says which command fixes it.
            raise HTTPException(status_code=409, detail=str(stale)) from stale

    @app.get("/api/imports")
    def imports() -> list[ImportRef]:
        """Every folder of the merchant's own files that has been imported.

        A separate route from `/api/runs` rather than a flag on it. An
        imported run has no answer key and so no scorecard, and a single
        endpoint returning two shapes would push that difference into the
        browser to be handled by a conditional nobody maintains.
        """
        return list(service.imports())

    @app.get("/api/imports/{slug}")
    def imported(slug: str) -> ImportView:
        try:
            return service.import_view(slug)
        except RunNotFoundError as missing:
            raise HTTPException(status_code=404, detail=str(missing)) from missing

    return app


app = create_app()
