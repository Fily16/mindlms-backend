from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# auto_error=False: el token también puede llegar como ?access_token=
# (EventSource del navegador no permite enviar cabeceras en el SSE).
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)

# Roles que pueden usar el Panel Psicológico (HU0002). Un "viewer" u otro
# rol queda fuera aunque sus credenciales sean válidas.
DASHBOARD_ROLES = {"psicologo", "admin"}
SIN_PERMISOS = "Tu usuario no tiene permisos para acceder al Panel Psicológico"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    access_token: Optional[str] = Query(None, include_in_schema=False),
) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = token or access_token
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return {"user_id": user_id, "role": payload.get("role", "viewer")}
    except JWTError:
        raise credentials_exception


async def require_dashboard_user(user: dict = Depends(get_current_user)) -> dict:
    """Exige sesión válida y un rol autorizado para el Panel Psicológico."""
    if user.get("role") not in DASHBOARD_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=SIN_PERMISOS)
    return user
