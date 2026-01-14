"""
Message history management using LangChain's RunnableWithMessageHistory.
"""
from typing import List
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from app.db.models.message import Message
from app.core.logging import get_logger

logger = get_logger(__name__)


class DjangoChatHistory(BaseChatMessageHistory):
    """Chat history backed by Django ORM."""
    
    def __init__(self, session_id: int):
        """
        Initialize chat history for a session.
        
        Args:
            session_id: Chat session ID
        """
        self.session_id = session_id
    
    @property
    def messages(self) -> List[BaseMessage]:
        """Retrieve messages from database."""
        try:
            db_messages = Message.objects.filter(
                session_id=self.session_id
            ).order_by('created_at')
            
            result = []
            for msg in db_messages:
                if msg.role == 'user':
                    result.append(HumanMessage(content=msg.content))
                elif msg.role == 'assistant':
                    aimessage = AIMessage(content=msg.content)
                    if msg.metadata:
                        aimessage.additional_kwargs = msg.metadata
                    result.append(aimessage)
                elif msg.role == 'system':
                    result.append(SystemMessage(content=msg.content))
            
            logger.debug(f"Loaded {len(result)} messages from database for session {self.session_id}")
            return result
        except Exception as e:
            logger.error(f"Error loading messages from database: {e}", exc_info=True)
            return []
    
    def add_message(self, message: BaseMessage) -> None:
        """Add message to database."""
        try:
            from app.services.chat_service import add_message
            
            role = 'user' if isinstance(message, HumanMessage) else 'assistant' if isinstance(message, AIMessage) else 'system'
            
            # Extract metadata if available
            metadata = {}
            if isinstance(message, AIMessage) and hasattr(message, 'additional_kwargs'):
                metadata = message.additional_kwargs or {}
            
            add_message(
                session_id=self.session_id,
                role=role,
                content=message.content if hasattr(message, 'content') else str(message),
                metadata=metadata
            )
            logger.debug(f"Added {role} message to database for session {self.session_id}")
        except Exception as e:
            logger.error(f"Error adding message to database: {e}", exc_info=True)
    
    def clear(self) -> None:
        """Clear message history."""
        try:
            Message.objects.filter(session_id=self.session_id).delete()
            logger.info(f"Cleared message history for session {self.session_id}")
        except Exception as e:
            logger.error(f"Error clearing message history: {e}", exc_info=True)


def get_session_history(session_id: str) -> BaseChatMessageHistory:
    """
    Factory function for RunnableWithMessageHistory.
    
    Args:
        session_id: Session ID as string (converted to int)
        
    Returns:
        DjangoChatHistory instance
    """
    return DjangoChatHistory(session_id=int(session_id))


def create_agent_with_history(agent: BaseAgent, session_id: int) -> RunnableWithMessageHistory:
    """
    Wrap agent with message history management.
    
    Args:
        agent: BaseAgent instance
        session_id: Chat session ID
        
    Returns:
        RunnableWithMessageHistory instance
    """
    def get_history(session_id_str: str) -> BaseChatMessageHistory:
        return DjangoChatHistory(session_id=int(session_id_str))
    
    return RunnableWithMessageHistory(
        agent.llm,
        lambda: get_history(str(session_id)),
        input_messages_key="messages",
        history_messages_key="history"
    )
