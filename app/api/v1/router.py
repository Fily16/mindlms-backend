from fastapi import APIRouter
from app.api.v1.endpoints import alerts, students, moodle, auth, ml

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Alertas"])
api_router.include_router(students.router, prefix="/students", tags=["Estudiantes"])
api_router.include_router(moodle.router, prefix="/moodle", tags=["Moodle LMS"])
api_router.include_router(ml.router, prefix="/ml", tags=["Machine Learning"])
