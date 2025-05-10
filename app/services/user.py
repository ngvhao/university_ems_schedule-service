from typing import List, Dict, Any
from databases import Database
from fastapi import HTTPException

from app.models.user import User

class UserService:
    @staticmethod
    async def get_user_by_id(user_id: int, db: Database) -> User:
        """
        Retrieve a user by their ID.

        Args:
            user_id (int): The ID of the user to retrieve.
            db (Database): The database connection.

        Returns:
            Dict[str, Any]: The user data.

        Raises:
            HTTPException: If the user is not found.
        """
        query = "SELECT * FROM users WHERE id = :id"
        user = await db.fetch_one(query, values={"id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return dict(user)

    @staticmethod
    async def get_all_users(db: Database) -> List[User]:
        """
        Retrieve all users from the database.

        Args:
            db (Database): The database connection.

        Returns:
            List[Dict[str, Any]]: List of user data.
        """
        query = "SELECT * FROM users"
        users = await db.fetch_all(query)
        return [dict(user) for user in users]