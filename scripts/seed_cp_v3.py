"""
Datos de prueba de los Casos de Prueba v3 (P20261006_CP_v3.xlsx).

Carga en PostgreSQL exactamente los usuarios, estudiantes y alertas que citan los
37 CP. Es idempotente: antes de cargar un conjunto borra SOLO los datos de los
estudiantes `estudiante.prueba*` (sus alertas, notas, historial e informes) y deja
intacto el resto de la base.

    python scripts/seed_cp_v3.py                        # conjunto referencia
    python scripts/seed_cp_v3.py --conjunto sin_alto
    python scripts/seed_cp_v3.py --conjunto vacio

Conjuntos:
  referencia  10 estudiantes y 12 alertas (Alto 2, Medio 3, Bajo 5).
              Estados: Pendiente 5, Revisada 3, En seguimiento 2, Resuelta 2.
              Lo usan casi todos los CP.
  sin_alto    Quita estudiante.prueba01 y 04 (y sus alertas A01, A02, A03, A07) y
              deja A06 y A12 en seguimiento: 8 estudiantes (Medio 3, Bajo 5) y
              8 alertas sin ninguna Resuelta. CP006-2, CP018-3, CP019-2, CP020-3.
  vacio       Sin estudiantes ni alertas. CP004-3, CP007-3, CP008-3, CP017-2.

El nivel que el panel muestra para un estudiante es el de su alerta más reciente,
por eso las fechas de A01/A03 (las más nuevas de prueba01 y prueba04) definen los
dos estudiantes en riesgo Alto.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db.postgresql import async_session, init_db  # noqa: E402
from app.models.alert import (  # noqa: E402
    Alert,
    AlertNote,
    AlertStatusChange,
    AlertStatus,
    EvaluationReport,
    RiskLevelDB,
)
from app.models.user import User, UserRole  # noqa: E402
from app.services.user_service import UserService  # noqa: E402

PREFIJO = "estudiante.prueba"

# Usuarios que piden los CP. La contraseña es la de los Datos de Prueba del Excel:
# el ambiente de pruebas es público para el revisor, no es un usuario real.
USUARIOS = [
    ("psicologo@mindlms.test", "MindLMS2026!", "Dra. Carmen Vega", "psicologo", True),
    ("viewer@mindlms.test", "MindLMS2026!", "Usuario Observador", "viewer", True),
    ("inactivo@mindlms.test", "MindLMS2026!", "Psicologo Inactivo", "psicologo", False),
]

# Textos de referencia del documento de CP (T-ALTO / T-MEDIO / T-BAJO). Se usan tal
# cual para que los marcadores lingüísticos del detalle (CP025) sean los esperados.
T_ALTO = (
    "Ya no puedo más con todo esto, me siento completamente solo y siento que "
    "nada tiene sentido."
)
T_MEDIO = (
    "Estoy muy estresado por los exámenes, no duermo bien y me preocupa "
    "desaprobar el curso."
)
T_BAJO = "Hola a todos, ¿alguien sabe hasta qué hora se puede subir la tarea del foro?"

TEXTO = {"alto": T_ALTO, "medio": T_MEDIO, "bajo": T_BAJO}
SCORE = {"alto": 0.91, "medio": 0.54, "bajo": 0.12}
CONFIANZA = {"alto": 0.96, "medio": 0.88, "bajo": 0.93}

# (alerta, estudiante, nivel, estado, fecha, fuente) — tabla de la sección Fase 3.
REFERENCIA = [
    ("A01", "01", "alto", "pendiente", "2026-10-01", "foro"),
    ("A02", "01", "medio", "revisada", "2026-09-20", "foro"),
    ("A03", "04", "alto", "en_seguimiento", "2026-09-28", "chat"),
    ("A04", "02", "medio", "pendiente", "2026-09-30", "foro"),
    ("A05", "05", "medio", "pendiente", "2026-09-29", "foro"),
    ("A06", "06", "medio", "resuelta", "2026-09-18", "foro"),
    ("A07", "04", "alto", "revisada", "2026-09-15", "foro"),
    ("A08", "07", "bajo", "pendiente", "2026-09-27", "foro"),
    ("A09", "08", "bajo", "pendiente", "2026-09-25", "chat"),
    ("A10", "09", "bajo", "revisada", "2026-09-24", "foro"),
    ("A11", "10", "bajo", "en_seguimiento", "2026-09-23", "foro"),
    ("A12", "11", "bajo", "resuelta", "2026-09-22", "foro"),
]

# sin_alto: fuera prueba01 y prueba04 (A01, A02, A03, A07); A06 y A12 pasan a seguimiento.
SIN_ALTO_FUERA = {"A01", "A02", "A03", "A07"}
SIN_ALTO_SEGUIMIENTO = {"A06", "A12"}


def filas(conjunto: str) -> list[tuple]:
    if conjunto == "vacio":
        return []
    if conjunto == "referencia":
        return REFERENCIA
    return [
        (a, e, n, "en_seguimiento" if a in SIN_ALTO_SEGUIMIENTO else s, f, src)
        for (a, e, n, s, f, src) in REFERENCIA
        if a not in SIN_ALTO_FUERA
    ]


async def asegurar_usuarios(session) -> None:
    """Crea los tres usuarios de prueba si faltan y corrige rol y estado si cambiaron."""
    svc = UserService(session)
    for email, password, nombre, rol, activo in USUARIOS:
        user = await svc.get_by_email(email)
        if user is None:
            user = await svc.create_user(email, password, nombre, rol)
            print(f"  usuario creado   {email} ({rol}, activo={activo})")
        else:
            print(f"  usuario existente {email}")
        cambios = []
        if user.full_name != nombre:
            user.full_name = nombre
            cambios.append("nombre")
        if user.role != UserRole(rol):
            user.role = UserRole(rol)
            cambios.append("rol")
        if bool(user.is_active) != activo:
            user.is_active = activo
            cambios.append("is_active")
        if cambios:
            await session.commit()
            print(f"    ajustado: {', '.join(cambios)}")


async def limpiar(session) -> None:
    """Borra solo lo que pertenece a los estudiantes de prueba."""
    ids = (
        (await session.execute(select(Alert.id).where(Alert.student_id.like(f"{PREFIJO}%"))))
        .scalars()
        .all()
    )
    if ids:
        await session.execute(delete(AlertNote).where(AlertNote.alert_id.in_(ids)))
        await session.execute(delete(AlertStatusChange).where(AlertStatusChange.alert_id.in_(ids)))
    await session.execute(
        delete(EvaluationReport).where(EvaluationReport.student_id.like(f"{PREFIJO}%"))
    )
    await session.execute(delete(Alert).where(Alert.student_id.like(f"{PREFIJO}%")))
    await session.commit()
    print(f"  borradas {len(ids)} alertas previas de {PREFIJO}*")


async def cargar(session, conjunto: str, psicologo: User) -> list[tuple]:
    datos = filas(conjunto)
    for codigo, est, nivel, estado, fecha, fuente in datos:
        creada = datetime.fromisoformat(f"{fecha}T09:30:00")
        alerta = Alert(
            id=f"cp-v3-{codigo.lower()}",
            student_id=f"{PREFIJO}{est}",
            student_name=f"Estudiante Prueba {est}",
            course_id="2",
            course_name="Curso de pruebas MindLMS",
            risk_level=RiskLevelDB(nivel),
            risk_score=SCORE[nivel],
            confidence=CONFIANZA[nivel],
            text_fragment=TEXTO[nivel],
            source=fuente,
            status=AlertStatus(estado),
            created_at=creada,
            updated_at=creada,
        )
        session.add(alerta)
        # Las alertas que ya no están pendientes llevan su transición en el
        # historial, para que el detalle muestre "Último cambio" (CP022, CP024).
        if estado != "pendiente":
            cambio = creada.replace(hour=15, minute=0)
            alerta.updated_at = cambio
            session.add(
                AlertStatusChange(
                    id=f"cp-v3-{codigo.lower()}-h1",
                    alert_id=alerta.id,
                    from_status=AlertStatus.PENDING,
                    to_status=AlertStatus(estado),
                    changed_by=psicologo.id,
                    changed_by_name=psicologo.full_name,
                    changed_at=cambio,
                )
            )
    await session.commit()
    return datos


def resumen(datos: list[tuple]) -> dict:
    """Conteos que verifican los CP: estudiantes por nivel y alertas por estado."""
    ultima: dict[str, tuple[str, str]] = {}
    for _, est, nivel, _, fecha, _ in datos:
        if est not in ultima or fecha > ultima[est][0]:
            ultima[est] = (fecha, nivel)
    niveles = {"alto": 0, "medio": 0, "bajo": 0}
    for _, nivel in ultima.values():
        niveles[nivel] += 1
    estados = {"pendiente": 0, "revisada": 0, "en_seguimiento": 0, "resuelta": 0}
    for _, _, _, estado, _, _ in datos:
        estados[estado] += 1
    return {
        "estudiantes": len(ultima),
        "alertas": len(datos),
        "niveles": niveles,
        "estados": estados,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--conjunto", choices=["referencia", "sin_alto", "vacio"], default="referencia")
    args = ap.parse_args()

    await init_db()
    async with async_session() as session:
        print(f"Conjunto: {args.conjunto}")
        await asegurar_usuarios(session)
        await limpiar(session)
        psicologo = await UserService(session).get_by_email("psicologo@mindlms.test")
        datos = await cargar(session, args.conjunto, psicologo)

    r = resumen(datos)
    print(f"  estudiantes: {r['estudiantes']}  alertas: {r['alertas']}")
    print(f"  por nivel:  {r['niveles']}")
    print(f"  por estado: {r['estados']}")
    if args.conjunto == "referencia":
        assert r["estudiantes"] == 10 and r["alertas"] == 12, r
        assert r["niveles"] == {"alto": 2, "medio": 3, "bajo": 5}, r["niveles"]
        assert r["estados"] == {
            "pendiente": 5,
            "revisada": 3,
            "en_seguimiento": 2,
            "resuelta": 2,
        }, r["estados"]
    elif args.conjunto == "sin_alto":
        assert r["estudiantes"] == 8 and r["alertas"] == 8, r
        assert r["niveles"] == {"alto": 0, "medio": 3, "bajo": 5}, r["niveles"]
        assert r["estados"]["resuelta"] == 0, r["estados"]
    print("[OK] datos cargados")


if __name__ == "__main__":
    asyncio.run(main())
