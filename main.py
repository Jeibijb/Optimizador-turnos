from __future__ import annotations

import logging
import time
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI(
    title="API de Optimización de Turnos Clínicos",
    description=(
        "Servicio de optimización para asignación automática de turnos clínicos. "
        "Soporta el sistema de cuarto turno chileno (Largo-Noche-Libre-Libre), "
        "restricciones de descanso, dotación por rol y preferencias del personal."
    ),
    version="1.0.0",
    contact={
        "name": "Turnos Clínicos API",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
def root():
    """Verifica que la API esté en línea."""
    return {"status": "ok", "message": "API de turnos clínicos activa"}


@app.get("/health", tags=["Health"])
def health():
    """Health check detallado."""
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
    """
    Genera una planificación óptima de turnos clínicos.

    - **staff / personal**: lista de miembros del equipo con sus restricciones.
    - **shifts / turnos**: lista de turnos a cubrir en el período.
    - **rules / reglas**: parámetros de negocio (descansos, cuarto turno, etc.).
    """
    logger.info(
        "Received scheduling request",
        extra={
            "staff_count": len(request.staff),
            "shift_count": len(request.shifts),
        },
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
        logger.exception("Unexpected error during schedule optimization")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al optimizar la planificación: {exc}",
        ) from exc

    logger.info(
        "Schedule optimization completed",
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
    summary="Validar datos de entrada",
    description="Valida el payload sin ejecutar el solver. Útil para detectar errores antes de optimizar.",
)
def validate_schedule_request(request: ScheduleRequest):
    """
    Valida el request sin ejecutar el optimizador.
    Devuelve un resumen de los datos recibidos.
    """
    roles = {member.role for member in request.staff}
    shift_kinds = {shift.kind for shift in request.shifts}

    return {
        "valid": True,
        "summary": {
            "staff_count": len(request.staff),
            "shift_count": len(request.shifts),
            "roles": sorted(roles),
            "shift_kinds": sorted(shift_kinds),
            "enforce_cuarto_turno": request.rules.enforce_cuarto_turno,
            "min_rest_hours": request.rules.min_rest_hours,
            "night_rest_hours": request.rules.night_rest_hours,
        },
    }

app.mount("/static", StaticFiles(directory="."), name="static")
@app.get("/ui")
def serve_ui():
    return FileResponse("index.html")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)