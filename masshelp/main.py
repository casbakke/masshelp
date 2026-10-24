"""FastAPI app: /health, /twilio/sms, /vapi/chat/completions, /files/{token}.

Run: uv run uvicorn masshelp.main:app --port 8000
Security: Twilio requests are signature-checked (TWILIO_VALIDATE), Vapi requests need
VAPI_SECRET when set, and /files links use random tokens that expire after 7 days.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlmodel import select

from masshelp.channels.sms import router as sms_router
from masshelp.channels.voice import router as voice_router
from masshelp.services import Services, build_services
from masshelp.store.models import FormPdf
from masshelp.util.dates import utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "services", None) is None:
            app.state.services = build_services()
        yield

    app = FastAPI(title="MassHelp", lifespan=lifespan)
    app.state.services = services
    app.include_router(sms_router)
    app.include_router(voice_router)

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/files/{token}")
    async def files(token: str, request: Request):
        svc = request.app.state.services
        with svc.db.session() as s:
            pdf = s.exec(select(FormPdf).where(FormPdf.token == token)).first()
        if pdf is None or pdf.expires_at < utcnow() or not Path(pdf.path).exists():
            raise HTTPException(status_code=404)
        return FileResponse(pdf.path, media_type="application/pdf", filename="MassHelp-AFVI-SAMPLE.pdf")

    return app


app = create_app()
