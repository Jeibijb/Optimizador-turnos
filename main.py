from __future__ import annotations

import logging
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from model import (
    ScheduleRequest,
    ScheduleResponse,
    SolverSettings,
    optimize_schedule,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Ruta absoluta al index.html, funciona tanto en local como en Railway/Render
BASE_DIR = Path(__file__).parent
INDEX_HTML = BASE_DIR / "index.html"

app = FastAPI(
    title="API de Optimización de Turnos Clínicos",
    description=(
        "Servicio de optimización para asignación automática de turnos clínicos. "
        "Soporta el sistema de cuarto turno chileno (Largo-Noche-Libre-Libre), "
        "restricciones de descanso, dotación por rol y preferencias del personal."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
@app.get("/ui", include_in_schema=False)
def serve_ui():
    """Sirve la interfaz web."""
    return FileResponse(INDEX_HTML)


@app.get("/health", tags=["Health"], summary="Health check")
def health():
    """Verifica que el servicio esté en línea."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "clinical-scheduling-api",
    }


@app.post(
    "/schedule",
    response_model=ScheduleResponse,
    status_code=status.HTTP_200_OK,
    tags=["Scheduling"],
    summary="Generar planificación de turnos",
    description=(
        "Recibe el personal, los turnos y las reglas de negocio, "
        "y devuelve una asignación óptima minimizando desequilibrios "
        "de carga, respetando descansos y preferencias del personal."
    ),
)
def create_schedule(
    request: ScheduleRequest,
    max_time_seconds: float = 10.0,
    num_workers: int = 8,
) -> ScheduleResponse:
    logger.info(
        "Scheduling request received",
        extra={"staff_count": len(request.staff), "shift_count": len(request.shifts)},
    )
    settings = SolverSettings(
        max_time_seconds=max_time_seconds,
        num_search_workers=num_workers,
    )
    try:
        response = optimize_schedule(
            staff=request.staff,
            shifts=request.shifts,
            rules=request.rules,
            settings=settings,
        )
    except Exception as exc:
        logger.exception("Unexpected error during optimization")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al optimizar la planificación: {exc}",
        ) from exc

    logger.info(
        "Scheduling request completed",
        extra={
            "status": response.status,
            "assignments": len(response.assignments),
            "solver_time": response.solver_time_seconds,
        },
    )
    return response


@app.post(
    "/schedule/validate",
    status_code=status.HTTP_200_OK,
    tags=["Scheduling"],
    summary="Validar datos de entrada sin ejecutar el solver",
)
def validate_schedule_request(request: ScheduleRequest):
    return {
        "valid": True,
        "summary": {
            "staff_count": len(request.staff),
            "shift_count": len(request.shifts),
            "roles": sorted({m.role for m in request.staff}),
            "shift_kinds": sorted({s.kind for s in request.shifts}),
            "enforce_cuarto_turno": request.rules.enforce_cuarto_turno,
            "min_rest_hours": request.rules.min_rest_hours,
            "night_rest_hours": request.rules.night_rest_hours,
        },
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)