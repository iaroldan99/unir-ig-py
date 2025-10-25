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
    last_message: Optional[ConversationMessage] = None


class SendMessageRequest(BaseModel):
    recipient_id: str
    text: str


class SendMessageResponse(BaseModel):
    message_id: str
    recipient_id: str


