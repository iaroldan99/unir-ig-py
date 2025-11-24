from typing import List, Optional

from pydantic import BaseModel


class ConversationMessage(BaseModel):
    id: str
    from_id: str
    to_id: str
    text: Optional[str] = None
    timestamp: int


class Conversation(BaseModel):
    id: str
    participants: List[str]
    last_message: Optional["ConversationMessage"] = None

class SendMessageRequest(BaseModel):
    # Formato nativo
    recipient_id: Optional[str] = None
    text: Optional[str] = None
    # Compat Core
    to: Optional[str] = None
    message: Optional[str] = None
    # (opcionales por si luego usás media)
    message_type: str = "text"
    media_url: Optional[str] = None

class SendMessageResponse(BaseModel):
    success: bool = True
    message_id: str
    recipient_id: str