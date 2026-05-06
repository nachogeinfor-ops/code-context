"""FastAPI router for /items — list, get, create, update, delete."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.item import ItemCreate, ItemRead, ItemUpdate
from app.services.item_service import ItemService

router = APIRouter()


def _svc(db: Session = Depends(get_db)) -> ItemService:  # noqa: B008
    return ItemService(db)


@router.get("/", response_model=list[ItemRead])
def list_items(  # noqa: B008
    skip: int = 0,
    limit: int = 20,
    svc: ItemService = Depends(_svc),  # noqa: B008
):
    """Return a paginated list of all items."""
    return svc.list_items(skip=skip, limit=limit)


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, svc: ItemService = Depends(_svc)):  # noqa: B008
    """Return a single item by ID."""
    item = svc.get_item_by_id(item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.post("/", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(  # noqa: B008
    data: ItemCreate,
    owner_id: int,
    svc: ItemService = Depends(_svc),  # noqa: B008
):
    """Create a new item belonging to the specified owner."""
    return svc.create_item(data, owner_id=owner_id)


@router.patch("/{item_id}", response_model=ItemRead)
def update_item(  # noqa: B008
    item_id: int,
    data: ItemUpdate,
    svc: ItemService = Depends(_svc),  # noqa: B008
):
    """Partially update an item's title or description."""
    item = svc.update_item(item_id, data)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, svc: ItemService = Depends(_svc)):  # noqa: B008
    """Delete an item by ID."""
    if not svc.delete_item(item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
