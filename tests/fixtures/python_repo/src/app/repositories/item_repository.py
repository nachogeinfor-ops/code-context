"""ItemRepository — low-level SQLAlchemy queries for Item rows."""

from sqlalchemy.orm import Session

from app.models.item import Item
from app.schemas.item import ItemUpdate


class ItemRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_by_id(self, item_id: int) -> Item | None:
        return self._db.get(Item, item_id)

    def list_all(self, skip: int = 0, limit: int = 20) -> list[Item]:
        return self._db.query(Item).offset(skip).limit(limit).all()

    def list_by_owner(self, owner_id: int, skip: int = 0, limit: int = 20) -> list[Item]:
        """Return all items that belong to *owner_id*."""
        return (
            self._db.query(Item).filter(Item.owner_id == owner_id).offset(skip).limit(limit).all()
        )

    def create(self, title: str, description: str | None, owner_id: int) -> Item:
        item = Item(title=title, description=description, owner_id=owner_id)
        self._db.add(item)
        self._db.commit()
        self._db.refresh(item)
        return item

    def update(self, item: Item, data: ItemUpdate) -> Item:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        self._db.commit()
        self._db.refresh(item)
        return item

    def delete(self, item: Item) -> None:
        self._db.delete(item)
        self._db.commit()
