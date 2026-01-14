"""
Event callback handler for streaming LLM tokens and task events.
"""
from typing import Dict, Any, List, Optional
from queue import Queue, Full as QueueFull
from langchain_core.callbacks import BaseCallbackHandler
from app.core.logging import get_logger

logger = get_logger(__name__)


class EventCallbackHandler(BaseCallbackHandler):
    """
    Callback handler that captures LLM tokens and task events,
    writing them to a thread-safe queue for consumption by the workflow.
    """
    
    def __init__(self, event_queue: Queue, status_messages: Optional[Dict[str, str]] = None):
        """
        Initialize the callback handler.
        
        Args:
            event_queue: Async queue to write events to
            status_messages: Optional mapping of task names to status messages
        """
        super().__init__()
        self.event_queue = event_queue
        self.status_messages = status_messages or {}
        self.current_chain = None
        self.chain_stack = []
        self.is_supervisor_llm = False
        self.supervisor_in_stack = False
        self.agent_names = {"greeter", "search", "gmail", "config", "process"}
        self.active_tasks = {}
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Track LLM start to identify supervisor routing calls."""
        try:
            if self.is_supervisor_llm:
                return
            
            run_name = kwargs.get("run_name", "")
            is_supervisor_context = self.supervisor_in_stack
            
            if not is_supervisor_context:
                for chain in self.chain_stack:
                    if chain and "supervisor" in str(chain).lower():
                        is_supervisor_context = True
                        self.supervisor_in_stack = True
                        break
            
            if not is_supervisor_context and run_name and "supervisor" in run_name.lower():
                is_supervisor_context = True
                self.supervisor_in_stack = True
            
            if not is_supervisor_context and self.current_chain and "supervisor" in str(self.current_chain).lower():
                is_supervisor_context = True
                self.supervisor_in_stack = True
            
            if not is_supervisor_context and isinstance(serialized, dict):
                serialized_str = str(serialized).lower()
                if "supervisor" in serialized_str or "supervisoragent" in serialized_str:
                    is_supervisor_context = True
                    self.supervisor_in_stack = True
            
            self.is_supervisor_llm = is_supervisor_context
        except Exception as e:
            logger.debug(f"Error in on_llm_start: {e}")
    
    def on_llm_end(self, response, **kwargs) -> None:
        """Reset supervisor flag."""
        self.is_supervisor_llm = False
    
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """Capture LLM token chunks, but skip supervisor routing tokens."""
        # Skip tokens from supervisor LLM
        if self.is_supervisor_llm:
            return
        
        # Additional validation: supervisor only outputs short agent names
        token_lower = token.strip().lower()
        if len(token_lower) <= 10 and token_lower in self.agent_names:
            if self.supervisor_in_stack or (self.current_chain and "supervisor" in str(self.current_chain).lower()):
                return
            for chain in self.chain_stack:
                if chain and "supervisor" in str(chain).lower():
                    return
        
        # Check chain context as fallback
        should_skip = False
        if self.current_chain and "supervisor" in str(self.current_chain).lower():
            should_skip = True
        if not should_skip:
            for chain in self.chain_stack:
                if chain and "supervisor" in str(chain).lower():
                    should_skip = True
                    break
        
        if should_skip:
            return
        
        if token:
            # Put token event in queue (thread-safe, non-blocking)
            try:
                self.event_queue.put_nowait({
                    "type": "token",
                    "value": token
                })
            except QueueFull:
                # Queue is full - drop token to prevent unbounded memory growth
                # Use debug level to avoid log spam under sustained load
                logger.debug(f"Event queue full, dropping token")
            except Exception as e:
                logger.error(f"[TOKEN_CALLBACK] Error queuing token: {e}", exc_info=True)
    
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs) -> None:
        """Capture chain/task start events."""
        try:
            chain_name = ""
            name_from_kwargs = kwargs.get("name", "")
            
            if serialized and isinstance(serialized, dict):
                chain_name = serialized.get("name", "")
                if not chain_name:
                    chain_id = serialized.get("id")
                    if isinstance(chain_id, list) and chain_id:
                        chain_name = chain_id[-1]
                    elif isinstance(chain_id, str):
                        chain_name = chain_id
            
            if not chain_name and name_from_kwargs:
                chain_name = name_from_kwargs
            
            run_name = kwargs.get("run_name", "")
            effective_name = run_name or chain_name or ""
            
            # Detect supervisor context early
            if effective_name and "supervisor" in effective_name.lower():
                self.supervisor_in_stack = True
                self.is_supervisor_llm = True
            
            self.chain_stack.append(effective_name)
            self.current_chain = effective_name
            
            # Extract task name
            task_name = None
            for known_task in self.status_messages.keys():
                if known_task.lower() in effective_name.lower() or effective_name.lower() in known_task.lower():
                    task_name = known_task
                    break
            
            # Send status update if task identified
            if task_name and task_name in self.status_messages:
                status = self.status_messages[task_name]
                if task_name not in self.active_tasks:
                    self.active_tasks[task_name] = {"status": status}
                    try:
                        self.event_queue.put_nowait({
                            "type": "update",
                            "data": {"status": status, "task": task_name}
                        })
                    except QueueFull:
                        logger.debug(f"Event queue full, dropping status update")
                    except Exception as e:
                        logger.debug(f"Error queuing status update: {e}")
        except Exception as e:
            logger.error(f"Error in on_chain_start: {e}", exc_info=True)
    
    def on_chain_end(self, outputs: Any, **kwargs) -> None:
        """Track chain end."""
        try:
            if self.chain_stack:
                popped = self.chain_stack.pop()
                self.current_chain = self.chain_stack[-1] if self.chain_stack else None
                
                # Check if this was a tracked task
                chain_to_check = str(popped) if popped else ""
                if chain_to_check:
                    for task_name in self.status_messages.keys():
                        task_lower = task_name.lower()
                        chain_lower = chain_to_check.lower()
                        if task_lower in chain_lower or chain_lower in task_lower:
                            if task_name in self.active_tasks:
                                task_info = self.active_tasks[task_name]
                                status_text = task_info.get("status", "")
                                
                                # Convert to past tense
                                past_tense_map = {
                                    "Processing with agent...": "Processed with agent",
                                    "Routing to agent...": "Routed to agent",
                                    "Loading conversation history...": "Loaded conversation history",
                                    "Executing tools...": "Executed tools",
                                    "Processing tool results...": "Processed tool results",
                                    "Checking if summarization needed...": "Checked if summarization needed",
                                    "Saving message...": "Saved message",
                                }
                                past_status = past_tense_map.get(status_text, status_text.replace("ing...", "ed").replace("ing", "ed"))
                                
                                try:
                                    self.event_queue.put_nowait({
                                        "type": "update",
                                        "data": {
                                            "status": past_status,
                                            "task": task_name,
                                            "is_completed": True
                                        }
                                    })
                                except QueueFull:
                                    logger.debug(f"Event queue full, dropping completion update")
                                except Exception as e:
                                    logger.debug(f"Error queuing completion update: {e}")
                                
                                del self.active_tasks[task_name]
                            break
                
                # Reset supervisor flag if popped
                if popped and "supervisor" in str(popped).lower():
                    self.supervisor_in_stack = any(
                        chain and "supervisor" in str(chain).lower()
                        for chain in self.chain_stack
                    )
                    if not self.supervisor_in_stack:
                        self.is_supervisor_llm = False
        except Exception:
            pass
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Capture tool execution start."""
        try:
            if serialized is None:
                return
            tool_name = serialized.get("name", "") if isinstance(serialized, dict) else ""
            if tool_name:
                try:
                    self.event_queue.put_nowait({
                        "type": "update",
                        "data": {"status": f"Executing {tool_name}...", "tool": tool_name}
                    })
                except QueueFull:
                    logger.debug(f"Event queue full, dropping tool start update")
                except Exception as e:
                    logger.debug(f"Error queuing tool start: {e}")
        except Exception as e:
            logger.error(f"Error in on_tool_start: {e}", exc_info=True)
    
    def on_tool_end(self, output: Any, **kwargs) -> None:
        """Tool execution completed."""
        try:
            tool_name = None
            if isinstance(kwargs.get("name"), str):
                tool_name = kwargs["name"]
            elif isinstance(kwargs.get("serialized"), dict):
                tool_name = kwargs["serialized"].get("name", "")
            
            if tool_name:
                try:
                    self.event_queue.put_nowait({
                        "type": "update",
                        "data": {"status": f"Executed {tool_name}", "tool": tool_name}
                    })
                except QueueFull:
                    logger.debug(f"Event queue full, dropping tool end update")
                except Exception as e:
                    logger.debug(f"Error queuing tool end: {e}")
        except Exception as e:
            logger.error(f"Error in on_tool_end: {e}", exc_info=True)
