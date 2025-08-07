from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.user import User

class UserService:
    @staticmethod
    async def get_user_by_id(user_id: int, db: AsyncSession) -> User:
        """
        Retrieve a user by their ID.

        Args:
            user_id (int): The ID of the user to retrieve.
            db (AsyncSession): The database session.

        Returns:
            User: The user data.

        Raises:
            HTTPException: If the user is not found.
        """
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    @staticmethod
    async def get_all_users(db: AsyncSession) -> List[User]:
        """
        Retrieve all users from the database.

        Args:
            db (AsyncSession): The database session.

        Returns:
            List[User]: List of user data.
        """
        stmt = select(User)
        result = await db.execute(stmt)
        users = result.scalars().all()
        return users
