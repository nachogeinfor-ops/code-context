"""In-memory key-value storage for sample_app."""


class Storage:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def put(self, key: str, value: str) -> None:
        self._data[key] = value

    def get(self, key: str) -> str | None:
        return self._data.get(key)
