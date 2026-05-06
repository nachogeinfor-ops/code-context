"""FastAPI router for /users — list, get, create, update, delete."""

from fastapi import APIRouter, Depends, HTTPException, status  # noqa: B008
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter()


def _svc(db: Session = Depends(get_db)) -> UserService:  # noqa: B008
    return UserService(db)


@router.get("/", response_model=list[UserRead])
def list_users(  # noqa: B008
    skip: int = 0,
    limit: int = 20,
    svc: UserService = Depends(_svc),  # noqa: B008
):
    """Return a paginated list of all users."""
    return svc.list_users(skip=skip, limit=limit)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, svc: UserService = Depends(_svc)):  # noqa: B008
    """Return a single user by ID."""
    user = svc.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, svc: UserService = Depends(_svc)):  # noqa: B008
    """Create a new user account."""
    try:
        return svc.create_user(data)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, data: UserUpdate, svc: UserService = Depends(_svc)):  # noqa: B008
    user = svc.update_user(user_id, data)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, svc: UserService = Depends(_svc)):  # noqa: B008
    """Delete a user by ID."""
    if not svc.delete_user(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
