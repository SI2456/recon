from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, auth, ca, client, clients, compat, dashboard, extract, fraud, graph, ingestion, invoices, messages, rag, reconciliation, reports
from app.api.deps import get_current_user
from app.api.ingestion import reset_stalled_processing
from app.core.config import settings
from app.db.models import User
from app.db.session import Base, engine, ensure_role_values, ensure_schema


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    ensure_role_values()
    reset_stalled_processing()

    api = FastAPI(title=settings.app_name, version="1.0.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.client_origin],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    api.include_router(ca.router, prefix="/api/ca", tags=["ca"])
    api.include_router(client.router, prefix="/api/client", tags=["client"])
    api.include_router(clients.router, prefix="/api/clients", tags=["clients"])
    api.include_router(invoices.router, prefix="/api/invoices", tags=["invoices"])
    api.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
    api.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
    api.include_router(extract.router, prefix="/api/extract", tags=["extract"])
    api.include_router(extract.files_router, prefix="/api/uploads", tags=["files"])
    api.include_router(reconciliation.router, prefix="/api/reconciliation", tags=["reconciliation"])
    api.include_router(fraud.router, prefix="/api/fraud", tags=["fraud"])
    api.include_router(graph.router, prefix="/api/graph", tags=["graph"])
    api.include_router(rag.router, prefix="/api/assistant", tags=["assistant"])
    api.include_router(reports.router, prefix="/api/reports", tags=["reports"])
    api.include_router(messages.router, prefix="/api/messages", tags=["messages"])
    api.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    api.include_router(compat.router, tags=["compat"])

    @api.get("/api/health")
    def health() -> dict:
        return {"ok": True, "service": settings.app_name, "environment": settings.environment}

    @api.get("/api/me")
    def me(user: User = Depends(get_current_user)) -> dict:
        return {
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "firmName": user.firm_name,
                "gstin": user.gstin,
                "icaiNumber": user.icai_number,
                "emailVerified": user.email_verified,
            }
        }

    return api


app = create_app()
