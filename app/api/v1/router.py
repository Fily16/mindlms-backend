from fastapi import APIRouter, Depends
from app.api.v1.endpoints import alerts, students, moodle, auth, ml
from app.core.security import require_dashboard_user

api_router = APIRouter()

# Todo lo que expone datos de estudiantes exige sesión de psicólogo (HU0002).
# /auth/login es público y /moodle/webhook se protege con la firma HMAC, por
# eso Moodle aplica la dependencia ruta por ruta.
_protegido = [Depends(require_dashboard_user)]

api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Alertas"], dependencies=_protegido)
api_router.include_router(students.router, prefix="/students", tags=["Estudiantes"], dependencies=_protegido)
api_router.include_router(moodle.router, prefix="/moodle", tags=["Moodle LMS"])
api_router.include_router(ml.router, prefix="/ml", tags=["Machine Learning"], dependencies=_protegido)
