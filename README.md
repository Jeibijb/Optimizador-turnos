# API de Optimización de Turnos Clínicos

Servicio REST construido con **FastAPI** y **OR-Tools** para la asignación automática de turnos clínicos, con soporte nativo para el **cuarto turno chileno** (Largo → Noche → Libre → Libre).

---

## Estructura del proyecto

```
.
├── main.py               # Aplicación FastAPI y endpoints
├── model.py              # Motor de optimización (OR-Tools CP-SAT)
├── requirements.txt      # Dependencias
└── example_request.json  # Payload de ejemplo listo para probar
```

---

## Instalación

```bash
# 1. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Instalar dependencias
pip install -r requirements.txt
```

---

## Levantar la API

```bash
python main.py
# o bien:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

La documentación interactiva queda disponible en:
- Swagger UI → http://localhost:8000/docs
- ReDoc      → http://localhost:8000/redoc

---

## Endpoints

| Método | Ruta                  | Descripción                                     |
|--------|-----------------------|-------------------------------------------------|
| GET    | `/`                   | Health check simple                             |
| GET    | `/health`             | Health check detallado                          |
| POST   | `/schedule`           | Genera la planificación óptima                  |
| POST   | `/schedule/validate`  | Valida el payload sin ejecutar el solver        |

### Query params opcionales en `/schedule`

| Parámetro          | Default | Descripción                              |
|--------------------|---------|------------------------------------------|
| `max_time_seconds` | `10.0`  | Tiempo máximo del solver en segundos     |
| `num_workers`      | `8`     | Threads paralelos del solver             |

---

## Ejemplo de uso

```bash
curl -X POST http://localhost:8000/schedule \
  -H "Content-Type: application/json" \
  -d @example_request.json
```

### Respuesta exitosa

```json
{
  "assignments": [
    { "staff_id": "enf_01", "shift_id": "largo_2025-07-01" },
    { "staff_id": "enf_02", "shift_id": "largo_2025-07-01" },
    ...
  ],
  "objective_value": 0.0,
  "status": "ok",
  "solver_time_seconds": 0.043,
  "message": "Planificación generada correctamente."
}
```

---

## Modelos de datos principales

### StaffMember / Personal

| Campo                    | Alias español              | Tipo                              | Descripción                          |
|--------------------------|----------------------------|-----------------------------------|--------------------------------------|
| `id`                     | —                          | `str`                             | Identificador único                  |
| `role`                   | `rol`                      | `str`                             | Ej: `"enfermero"`, `"TENS"`          |
| `seniority`              | `experiencia`              | `senior \| intermedio \| junior`  | Nivel de experiencia                 |
| `max_hours`              | `maximo_horas`             | `int`                             | Horas máximas en el período          |
| `unavailable_dates`      | `fechas_no_disponibles`    | `list[date]`                      | Fechas bloqueadas                    |
| `requested_days_off`     | `dias_solicitados_libres`  | `list[date]`                      | Días preferidos libres (soft)        |
| `previous_shift_kind`    | `tipo_turno_previo`        | `largo \| noche \| otro \| null`  | Para respetar descanso entre períodos|
| `previous_shift_end`     | `fin_turno_previo`         | `datetime \| null`                | Fin del turno anterior al período    |

### Shift / Turno

| Campo              | Alias español        | Tipo                           | Descripción                          |
|--------------------|----------------------|--------------------------------|--------------------------------------|
| `id`               | —                    | `str`                          | Identificador único                  |
| `kind`             | `tipo`               | `dia \| largo \| noche \| otro`| Tipo de turno                        |
| `start`            | `inicio`             | `datetime`                     | Inicio del turno                     |
| `end`              | `fin`                | `datetime`                     | Fin del turno                        |
| `required_by_role` | `dotacion_por_rol`   | `dict[str, int]`               | Dotación requerida por rol           |
| `required_staff`   | `dotacion_requerida` | `int`                          | Dotación total (sin distinción rol)  |
| `min_senior_by_role`| `minimo_senior_por_rol`| `dict[str, int]`             | Mínimo seniors por rol               |

### SchedulingRules / Reglas

| Campo                        | Alias español                  | Default | Descripción                                    |
|------------------------------|--------------------------------|---------|------------------------------------------------|
| `min_rest_hours`             | `descanso_minimo_horas`        | `12`    | Descanso mínimo entre turnos                   |
| `night_rest_hours`           | `descanso_post_noche_horas`    | `36`    | Descanso obligatorio post turno noche          |
| `enforce_one_shift_per_day`  | `un_turno_por_dia`             | `true`  | Máximo un turno por día por persona            |
| `enforce_cuarto_turno`       | `cuarto_turno`                 | `false` | Activa lógica de cuarto turno                  |
| `prefer_cuarto_turno_pattern`| `preferir_patron_cuarto_turno` | `true`  | Prefiere Largo→Noche como objetivo blando      |
| `force_cuarto_turno_pairing` | `forzar_pareja_cuarto_turno`   | `false` | Fuerza el par Largo→Noche (restricción dura)   |

---

## Cuarto turno chileno

El sistema cuarto turno asigna a cada persona el ciclo **Largo (24h) → Noche (12h) → Libre → Libre**, rotando entre grupos.

- `enforce_cuarto_turno: true` + `prefer_cuarto_turno_pattern: true` → el solver **prefiere** el patrón pero puede romperlo si hay ausencias.
- `enforce_cuarto_turno: true` + `force_cuarto_turno_pairing: true` → el par Largo→Noche es **obligatorio** (puede resultar en infactibilidad si hay vacaciones o bajas).

---

## Objetivo del solver

El solver minimiza (en orden de prioridad):

1. **Desequilibrio de carga** entre compañeros del mismo rol (×100)
2. **Desequilibrio de turnos de fin de semana** por rol (×25)
3. **Días solicitados libres no respetados** (×10)
4. **Rupturas del patrón cuarto turno** (×40, solo si aplica)
