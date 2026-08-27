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
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from milan.api.service import (
    ImportRef,
    ImportView,
    PlanView,
    RunNotFoundError,
    RunRef,
    RunView,
    Service,
)
from milan.api.staging import StagingError, UnknownStagingError
from milan.ingest.build import NotReadyError
from milan.llm.keyfile import load_keyfile
from milan.persistence.store import StaleDatasetError

load_keyfile()
"""Read `engine/.env` before the app is built, for the same reason the CLI
does: anything already exported wins, and nothing here prints a value."""

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


UploadedFiles = Annotated[list[UploadFile], File()]
"""The multipart field the wizard posts under.

Written as an annotated alias rather than a `File(...)` default, because a
function call in a default is evaluated once at import and shared by every
request that follows.
"""


class Answers(BaseModel):
    """Answers to the import's questions, addressed `file:field`."""

    model_config = ConfigDict(frozen=True)

    answers: dict[str, str]


class Commit(BaseModel):
    """What to call the import once it is kept."""

    model_config = ConfigDict(frozen=True)

    name: str = ""


class Committed(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str


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
        # POST and DELETE were added for the import wizard, and the addition is
        # worth a line rather than a shrug. Until it, this API could only be
        # read from - a page that got past the origin check could learn a
        # merchant's settlement figures and nothing more. It can now stage an
        # upload and delete a staged one.
        #
        # What it still cannot do is touch a stored run: there is no route
        # that writes to `data/runs`, and committing an import creates a new
        # archive rather than modifying anything. The origin list stays as
        # narrow as it was, which is the control actually doing the work here.
        allow_methods=["GET", "POST", "DELETE"],
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

    @app.post("/api/uploads")
    async def upload(files: UploadedFiles) -> PlanView:
        """Take a merchant's files and say what they appear to be.

        Nothing is reconciled here and nothing is stored beyond the staging
        directory. What comes back is a reading of the files with every
        unanswered question in it - the same refuse-and-ask contract the
        command line has, over HTTP.
        """
        try:
            return service.stage([(item.filename or "", await item.read()) for item in files])
        except StagingError as refused:
            # 422, not 500. Nothing went wrong with the server; the upload was
            # refused, and the message says what would make it acceptable.
            raise HTTPException(status_code=422, detail=str(refused)) from refused

    @app.post("/api/uploads/{staged_id}/files")
    async def add_files(staged_id: str, files: UploadedFiles) -> PlanView:
        """Add more files to an upload that is already open.

        The route that stops a merchant losing their first file. Without it,
        picking a settlement report and then picking a bank statement produced
        a plan holding the statement alone, with the report silently gone and
        an error saying there was nothing to reconcile against.
        """
        try:
            return service.add_to(
                staged_id, [(item.filename or "", await item.read()) for item in files]
            )
        except UnknownStagingError as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from gone
        except StagingError as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused

    @app.get("/api/uploads/{staged_id}")
    def staged(staged_id: str) -> PlanView:
        try:
            return service.staged(staged_id)
        except UnknownStagingError as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from gone

    @app.post("/api/uploads/{staged_id}/answers")
    def answer(staged_id: str, given: Answers) -> PlanView:
        """Answer one or more of the questions, and get the whole plan back.

        The whole plan rather than a delta, because one answer can open or
        close another - pinning a date column immediately raises the question
        of which way round to read it.
        """
        try:
            return service.answer(staged_id, given.answers)
        except UnknownStagingError as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from gone
        except StagingError as refused:
            raise HTTPException(status_code=422, detail=str(refused)) from refused

    @app.post("/api/uploads/{staged_id}/commit")
    def commit(staged_id: str, named: Commit) -> Committed:
        """Reconcile the staged files and keep the result."""
        try:
            return Committed(slug=service.commit(staged_id, named.name))
        except UnknownStagingError as gone:
            raise HTTPException(status_code=404, detail=str(gone)) from gone
        except NotReadyError as unanswered:
            # The wizard should not have offered the button, but a client is
            # not a place to enforce anything. 409: the request is well formed
            # and the thing it asks for is not true yet.
            raise HTTPException(status_code=409, detail=str(unanswered)) from unanswered

    @app.delete("/api/uploads/{staged_id}")
    def discard(staged_id: str) -> dict[str, str]:
        """Throw the upload away. Always succeeds - discarding what is already
        gone is the outcome the caller wanted."""
        service.discard(staged_id)
        return {"status": "discarded"}

    return app


app = create_app()
