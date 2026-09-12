"""Servicio de gestión de usuarios."""

import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.core.security import get_password_hash, verify_password


class UserService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_user(self, email: str, password: str, full_name: str, role: str = "viewer") -> User:
        user = User(
            id=str(uuid.uuid4()),
            email=email,
            hashed_password=get_password_hash(password),
            full_name=full_name,
            role=UserRole(role),
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def authenticate(self, email: str, password: str) -> User | None:
        user = await self.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user

    async def get_all_users(self) -> list[User]:
        result = await self.session.execute(select(User).where(User.is_active == True))
        return list(result.scalars().all())
