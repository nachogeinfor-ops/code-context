"""ItemService — business logic layer for item management."""

from sqlalchemy.orm import Session

from app.models.item import Item
from app.repositories.item_repository import ItemRepository
from app.schemas.item import ItemCreate, ItemUpdate


class ItemService:
    def __init__(self, db: Session) -> None:
        self._repo = ItemRepository(db)

    def create_item(self, data: ItemCreate, owner_id: int) -> Item:
        """Create a new item belonging to *owner_id*."""
        return self._repo.create(title=data.title, description=data.description, owner_id=owner_id)

    def get_item_by_id(self, item_id: int) -> Item | None:
        return self._repo.get_by_id(item_id)

    def list_items(self, skip: int = 0, limit: int = 20) -> list[Item]:
        return self._repo.list_all(skip=skip, limit=limit)

    def list_items_for_user(self, owner_id: int, skip: int = 0, limit: int = 20) -> list[Item]:
        """Return all items owned by *owner_id*."""
        return self._repo.list_by_owner(owner_id=owner_id, skip=skip, limit=limit)

    def update_item(self, item_id: int, data: ItemUpdate) -> Item | None:
        item = self._repo.get_by_id(item_id)
        if item is None:
            return None
        return self._repo.update(item, data)

    def delete_item(self, item_id: int) -> bool:
        item = self._repo.get_by_id(item_id)
        if item is None:
            return False
        self._repo.delete(item)
        return True
