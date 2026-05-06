"""UserRepository — low-level SQLAlchemy queries for User rows."""

from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserUpdate


class UserRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, user_id: int) -> User | None:
        return self._db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        """Find a user by their email address."""
        return self._db.query(User).filter(User.email == email).first()

    def get_by_username(self, username: str) -> User | None:
        return self._db.query(User).filter(User.username == username).first()

    def list_all(self, skip: int = 0, limit: int = 20) -> list[User]:
        return self._db.query(User).offset(skip).limit(limit).all()

    def create(self, email: str, username: str, hashed_password: str) -> User:
        user = User(email=email, username=username, hashed_password=hashed_password)
        self._db.add(user)
        self._db.commit()
        self._db.refresh(user)
        return user

    def update(self, user: User, data: UserUpdate) -> User:
        for field, value in data.model_dump(exclude_unset=True, exclude={"password"}).items():
            setattr(user, field, value)
        self._db.commit()
        self._db.refresh(user)
        return user

    def set_password(self, user: User, hashed_password: str) -> None:
        user.hashed_password = hashed_password
        self._db.commit()

    def delete(self, user: User) -> None:
        self._db.delete(user)
        self._db.commit()
