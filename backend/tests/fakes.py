"""In-memory stand-ins for the memory ports, for API tests that need no database."""

from personal_kb.services.memory_ports import SpecDocument


class InMemoryDocumentStore:
    """The DocumentStore port on a dict; specs come back sorted by id, as the Postgres store returns them."""

    def __init__(self) -> None:
        self._docs: dict[str, SpecDocument] = {}

    async def ensure(self) -> None:
        return None

    async def put(self, spec_id: str, *, title: str, content: str, project_id: str = "Personal-KB") -> None:
        self._docs[spec_id] = SpecDocument(spec_id=spec_id, title=title, content=content, project_id=project_id)

    async def get(self, spec_id: str) -> SpecDocument | None:
        return self._docs.get(spec_id)

    async def all(self) -> list[SpecDocument]:
        return [self._docs[k] for k in sorted(self._docs)]

    async def delete(self, spec_id: str) -> None:
        self._docs.pop(spec_id, None)
