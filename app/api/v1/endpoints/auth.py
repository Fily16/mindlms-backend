"""Endpoint de autenticación."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgresql import get_session
from app.services.user_service import UserService
from app.core.security import create_access_token, get_current_user
from app.schemas.auth import Token

router = APIRouter()


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
):
    svc = UserService(session)
    user = await svc.authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user.id, "role": user.role.value})
    return Token(access_token=token)


@router.get("/me")
async def get_me(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Devuelve los datos del usuario autenticado."""
    svc = UserService(session)
    user = await svc.get_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value,
    }
