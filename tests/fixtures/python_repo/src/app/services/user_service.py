"""UserService — business logic layer for user management."""

from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import hash_password


class UserService:
    def __init__(self, db: Session) -> None:
        self._repo = UserRepository(db)

    def create_user(self, data: UserCreate) -> User:
        """Create a new user, hashing the password before persistence."""
        if self._repo.get_by_email(data.email):
            raise ValueError(f"Email {data.email!r} is already registered")
        if self._repo.get_by_username(data.username):
            raise ValueError(f"Username {data.username!r} is already taken")
        hashed = hash_password(data.password)
        return self._repo.create(email=data.email, username=data.username, hashed_password=hashed)

    def get_user_by_id(self, user_id: int) -> User | None:
        """Return user by primary key, or None."""
        return self._repo.get_by_id(user_id)

    def get_user_by_email(self, email: str) -> User | None:
        return self._repo.get_by_email(email)

    def list_users(self, skip: int = 0, limit: int = 20) -> list[User]:
        return self._repo.list_all(skip=skip, limit=limit)

    def update_user(self, user_id: int, data: UserUpdate) -> User | None:
        """Partially update user fields; re-hashes password if provided."""
        user = self._repo.get_by_id(user_id)
        if user is None:
            return None
        if data.password is not None:
            data = data.model_copy(update={"password": None})
            self._repo.set_password(user, hash_password(data.password or ""))
        return self._repo.update(user, data)

    def delete_user(self, user_id: int) -> bool:
        """Delete user by id; return True if found and deleted."""
        user = self._repo.get_by_id(user_id)
        if user is None:
            return False
        self._repo.delete(user)
        return True
