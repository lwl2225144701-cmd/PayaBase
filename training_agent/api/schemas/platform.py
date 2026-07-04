from pydantic import BaseModel


class PlatformCallbackResponse(BaseModel):
    status: str = "success"
    conversation_id: str | None = None
    message_id: str | None = None
    duplicated: bool = False
