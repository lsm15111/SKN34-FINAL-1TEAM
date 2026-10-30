import uuid

from pydantic import BaseModel


class FileOut(BaseModel):
    id: uuid.UUID
    kind: str
    filename: str
    content_type: str
    size: int
