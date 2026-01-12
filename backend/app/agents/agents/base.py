"""
Base agent class for all agents.
"""
from abc import ABC, abstractmethod
from typing import List, Iterator
import os
import json
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.tools import BaseTool
from app.agents.config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    LANGCHAIN_TRACING_V2,
    LANGCHAIN_PROJECT,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Enable LangSmith tracing if configured (optional, for compatibility)
if LANGCHAIN_TRACING_V2:
    os.environ['LANGCHAIN_TRACING_V2'] = 'true'
    os.environ['LANGCHAIN_PROJECT'] = LANGCHAIN_PROJECT
    logger.info(f"LangSmith tracing enabled for project: {LANGCHAIN_PROJECT}")


class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    Provides common functionality for LLM integration and tool handling.
    """
    
    def __init__(self, name: str, description: str, temperature: float = 0.7, model_name: str = None):
        """
        Initialize base agent.
        
        Args:
            name: Agent name/identifier
            description: Agent description for routing
            temperature: LLM temperature
            model_name: Optional model name (defaults to OPENAI_MODEL)
        """
        self.name = name
        self.description = description
        self._model_name = model_name or OPENAI_MODEL
        
        # LLM initialization - callbacks are passed via config at invocation time
        # This allows LangGraph to handle callback propagation automatically
        self.llm = ChatOpenAI(
            model=self._model_name,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
            streaming=True,
            stream_usage=True,  # Enable token usage in streaming responses
        )
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get system prompt for this agent."""
        pass
    
    def get_tools(self) -> List[BaseTool]:
        """
        Get tools available to this agent.
        Override in subclasses to provide agent-specific tools.
        """
        return []
    
    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        """
        Invoke agent with messages.
        
        Args:
            messages: List of conversation messages
            **kwargs: Additional arguments including config (callbacks, run_id, metadata)
            
        Returns:
            AI response message
        """
        try:
            logger.debug(f"Invoking {self.name} agent with {len(messages)} messages")
            
            # Add system prompt as first message if not present
            system_prompt = self.get_system_prompt()
            if system_prompt:
                # Check if system message already exists
                if not messages or not isinstance(messages[0], BaseMessage) or messages[0].content != system_prompt:
                    from langchain_core.messages import SystemMessage
                    messages = [SystemMessage(content=system_prompt)] + messages
            
            # Get tools for this agent
            tools = self.get_tools()
            
            # Bind tools to LLM if available
            if tools:
                llm_with_tools = self.llm.bind_tools(tools)
                logger.debug(f"{self.name} agent using {len(tools)} tools")
            else:
                llm_with_tools = self.llm
            
            # Invoke LLM - pass through config from kwargs
            # LangGraph handles callback propagation automatically
            # NOTE: For streaming to work, we need to use .stream() instead of .invoke()
            # However, .invoke() is simpler for tasks. We'll use .stream() and collect chunks
            # to ensure callbacks (on_llm_new_token) are called for token streaming
            invoke_kwargs = {}
            if 'config' in kwargs:
                invoke_kwargs['config'] = kwargs['config']
            
            # Use stream() to ensure token callbacks are triggered
            # This allows EventCallbackHandler.on_llm_new_token() to be called
            # Collect chunks into a single AIMessage
            from langchain_core.messages import AIMessage
            accumulated_content = ""
            tool_calls_accumulated = []
            final_response = None
            
            logger.debug(f"[AGENT_INVOKE] Starting stream for {self.name} agent to trigger token callbacks")
            chunk_count = 0
            for chunk in llm_with_tools.stream(messages, **invoke_kwargs):
                chunk_count += 1
                chunk_type = type(chunk).__name__
                # Chunk is typically an AIMessageChunk or AIMessage
                if hasattr(chunk, 'content') and chunk.content:
                    accumulated_content += chunk.content
                # Collect tool calls if present (they may come in separate chunks)
                # CRITICAL: LangChain streams tool calls incrementally:
                # - tool_call_chunks: List of ToolCallChunk with index, args as STRING (incremental)
                # - tool_calls: Parsed tool calls (best-effort, may be incomplete)
                # We need to use tool_call_chunks to properly merge incremental args
                tool_call_chunks = getattr(chunk, 'tool_call_chunks', None) or []
                if tool_call_chunks:
                    logger.info(f"[AGENT_INVOKE] {self.name} agent: Found {len(tool_call_chunks)} tool_call_chunks in chunk #{chunk_count} (type={chunk_type})")
                    for tcc in tool_call_chunks:
                        # ToolCallChunk has: name, args (STRING), id, index
                        tcc_index = getattr(tcc, 'index', None) if hasattr(tcc, 'index') else (tcc.get('index') if isinstance(tcc, dict) else None)
                        tcc_id = getattr(tcc, 'id', None) if hasattr(tcc, 'id') else (tcc.get('id') if isinstance(tcc, dict) else None)
                        tcc_name = getattr(tcc, 'name', None) if hasattr(tcc, 'name') else (tcc.get('name') if isinstance(tcc, dict) else None)
                        tcc_args_str = getattr(tcc, 'args', '') if hasattr(tcc, 'args') else (tcc.get('args', '') if isinstance(tcc, dict) else '')
                        
                        # Find existing tool call by ID or index
                        existing_idx = None
                        for idx, existing_tc in enumerate(tool_calls_accumulated):
                            existing_id = existing_tc.get('id') if isinstance(existing_tc, dict) else (getattr(existing_tc, 'id', None) if hasattr(existing_tc, 'id') else None)
                            existing_index = existing_tc.get('index') if isinstance(existing_tc, dict) else (getattr(existing_tc, 'index', None) if hasattr(existing_tc, 'index') else None)
                            
                            # Match by ID if both have IDs, otherwise match by index
                            if tcc_id and existing_id and existing_id == tcc_id:
                                existing_idx = idx
                                break
                            elif tcc_index is not None and existing_index is not None and existing_index == tcc_index:
                                existing_idx = idx
                                break
                        
                        if existing_idx is not None:
                            # Merge incremental args (args is a STRING that gets concatenated)
                            existing_tc = tool_calls_accumulated[existing_idx]
                            if isinstance(existing_tc, dict):
                                existing_args_str = existing_tc.get('_args_str', '')  # Store raw args string
                                existing_args_str += tcc_args_str  # Concatenate incremental args
                                existing_tc['_args_str'] = existing_args_str
                                
                                # Update ID if missing but present in chunk
                                if not existing_tc.get('id') and tcc_id:
                                    existing_tc['id'] = tcc_id
                                # Update name if missing but present in chunk
                                if not existing_tc.get('name') and tcc_name:
                                    existing_tc['name'] = tcc_name
                                # Update index if missing
                                if 'index' not in existing_tc and tcc_index is not None:
                                    existing_tc['index'] = tcc_index
                                
                                # Try to parse args as JSON (may be incomplete during streaming)
                                try:
                                    if existing_args_str.strip():
                                        parsed_args = json.loads(existing_args_str)
                                        existing_tc['args'] = parsed_args
                                except (json.JSONDecodeError, ValueError):
                                    # Args not complete yet, keep as string
                                    pass
                                
                                logger.info(f"[AGENT_INVOKE] {self.name} agent: Merged incremental args for tool call index={tcc_index} id={tcc_id} from chunk #{chunk_count}: args_str_length={len(existing_args_str)}")
                            else:
                                # Handle ToolCall object
                                if not hasattr(existing_tc, '_args_str'):
                                    existing_tc._args_str = ''
                                existing_tc._args_str += tcc_args_str
                                
                                if not getattr(existing_tc, 'id', None) and tcc_id:
                                    existing_tc.id = tcc_id
                                if not getattr(existing_tc, 'name', None) and tcc_name:
                                    existing_tc.name = tcc_name
                                
                                try:
                                    if existing_tc._args_str.strip():
                                        parsed_args = json.loads(existing_tc._args_str)
                                        existing_tc.args = parsed_args
                                except (json.JSONDecodeError, ValueError):
                                    pass
                        else:
                            # New tool call chunk - create entry
                            import json
                            tc_dict = {
                                'id': tcc_id,
                                'name': tcc_name,
                                'index': tcc_index,
                                '_args_str': tcc_args_str,  # Store raw string for incremental building
                                'type': 'tool_call'
                            }
                            
                            # Try to parse args if complete
                            try:
                                if tcc_args_str.strip():
                                    parsed_args = json.loads(tcc_args_str)
                                    tc_dict['args'] = parsed_args
                                else:
                                    tc_dict['args'] = {}
                            except (json.JSONDecodeError, ValueError):
                                # Args incomplete, will be merged later
                                tc_dict['args'] = {}
                            
                            tool_calls_accumulated.append(tc_dict)
                            logger.info(f"[AGENT_INVOKE] {self.name} agent: Collected tool call chunk from chunk #{chunk_count}: name={tcc_name}, id={tcc_id}, index={tcc_index}, args_str_length={len(tcc_args_str)}")
                
                # Also check tool_calls for backwards compatibility (parsed tool calls)
                elif hasattr(chunk, 'tool_calls') and chunk.tool_calls:
                    logger.info(f"[AGENT_INVOKE] {self.name} agent: Found {len(chunk.tool_calls)} tool_calls (parsed) in chunk #{chunk_count} (type={chunk_type})")
                    for tc in chunk.tool_calls:
                        # Handle both dict and ToolCall object formats
                        tc_id = tc.get('id') if isinstance(tc, dict) else (getattr(tc, 'id', None) if hasattr(tc, 'id') else None)
                        tc_name = tc.get('name') if isinstance(tc, dict) else getattr(tc, 'name', None)
                        tc_args = tc.get('args') if isinstance(tc, dict) else getattr(tc, 'args', None)
                        
                        # Convert to dict for consistent handling
                        if not isinstance(tc, dict):
                            tc_dict = {
                                'id': tc_id,
                                'name': tc_name,
                                'args': tc_args if tc_args else {},
                                'type': 'tool_call'
                            }
                        else:
                            tc_dict = tc.copy()
                            if 'args' not in tc_dict or not tc_dict['args']:
                                tc_dict['args'] = {}
                        
                        if tc_id:
                            # Find existing tool call by ID
                            existing_idx = None
                            for idx, existing_tc in enumerate(tool_calls_accumulated):
                                existing_id = existing_tc.get('id') if isinstance(existing_tc, dict) else (getattr(existing_tc, 'id', None) if hasattr(existing_tc, 'id') else None)
                                if existing_id == tc_id:
                                    existing_idx = idx
                                    break
                            
                            if existing_idx is not None:
                                # Merge args from parsed tool call (complete args)
                                existing_tc = tool_calls_accumulated[existing_idx]
                                if isinstance(existing_tc, dict):
                                    # If we have incremental args string, try to parse it first
                                    if '_args_str' in existing_tc and existing_tc['_args_str']:
                                        try:
                                            parsed_from_str = json.loads(existing_tc['_args_str'])
                                            existing_tc['args'] = parsed_from_str
                                        except (json.JSONDecodeError, ValueError):
                                            pass
                                    # Update with complete args from parsed tool call
                                    if tc_dict.get('args'):
                                        existing_tc['args'] = tc_dict['args']
                                    if not existing_tc.get('name') and tc_dict.get('name'):
                                        existing_tc['name'] = tc_dict['name']
                                else:
                                    if hasattr(existing_tc, '_args_str') and existing_tc._args_str:
                                        try:
                                            parsed_from_str = json.loads(existing_tc._args_str)
                                            existing_tc.args = parsed_from_str
                                        except (json.JSONDecodeError, ValueError):
                                            pass
                                    if tc_dict.get('args'):
                                        existing_tc.args = tc_dict['args']
                                    if not getattr(existing_tc, 'name', None) and tc_dict.get('name'):
                                        existing_tc.name = tc_dict['name']
                                
                                logger.info(f"[AGENT_INVOKE] {self.name} agent: Merged parsed args for tool call id={tc_id} from chunk #{chunk_count}: args={tc_dict.get('args')}")
                            else:
                                # New tool call, add it
                                tool_calls_accumulated.append(tc_dict)
                                logger.info(f"[AGENT_INVOKE] {self.name} agent: Collected parsed tool call from chunk #{chunk_count}: name={tc_name}, id={tc_id}, args={tc_args}")
                # Keep reference to last chunk for metadata
                final_response = chunk
            
            logger.info(f"[AGENT_INVOKE] {self.name} agent: Stream completed with {chunk_count} chunks, accumulated_content_length={len(accumulated_content)}, tool_calls_accumulated={len(tool_calls_accumulated)}, final_response_type={type(final_response).__name__ if final_response else 'None'}")
            
            # Construct final AIMessage from accumulated content
            # CRITICAL: Always use accumulated tool_calls if available
            # Tool calls may come in separate chunks and need to be merged
            # Note: final_response might be AIMessageChunk, not AIMessage
            from langchain_core.messages import AIMessageChunk
            
            if final_response and isinstance(final_response, AIMessage):
                response = final_response
                # Update content if we accumulated it
                if accumulated_content:
                    response.content = accumulated_content
                # CRITICAL: Always merge accumulated tool_calls (they may come in separate chunks)
                if tool_calls_accumulated:
                    # Merge with existing tool_calls, avoiding duplicates by ID
                    existing_tool_calls = response.tool_calls or []
                    # Convert existing tool_calls to dict format for consistent comparison
                    existing_tool_calls_dicts = []
                    for tc in existing_tool_calls:
                        if isinstance(tc, dict):
                            existing_tool_calls_dicts.append(tc)
                        else:
                            # Convert ToolCall object to dict
                            existing_tool_calls_dicts.append({
                                'id': getattr(tc, 'id', None),
                                'name': getattr(tc, 'name', None),
                                'args': getattr(tc, 'args', {}),
                                'type': 'tool_call'
                            })
                    
                    existing_ids = {tc.get('id') for tc in existing_tool_calls_dicts if tc.get('id')}
                    for tc in tool_calls_accumulated:
                        # Convert to dict if needed and finalize args parsing
                        if not isinstance(tc, dict):
                            # Handle ToolCall object
                            if hasattr(tc, '_args_str') and tc._args_str:
                                try:
                                    parsed_args = json.loads(tc._args_str)
                                    tc.args = parsed_args
                                except (json.JSONDecodeError, ValueError):
                                    tc.args = {}
                            tc = {
                                'id': getattr(tc, 'id', None),
                                'name': getattr(tc, 'name', None),
                                'args': getattr(tc, 'args', {}),
                                'type': 'tool_call'
                            }
                        else:
                            # Finalize args parsing from incremental string if present
                            if '_args_str' in tc and tc['_args_str']:
                                try:
                                    parsed_args = json.loads(tc['_args_str'])
                                    tc['args'] = parsed_args
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.warning(f"[AGENT_INVOKE] {self.name} agent: Failed to parse args string '{tc['_args_str']}': {e}")
                                    tc['args'] = {}
                                # Remove temporary _args_str
                                tc.pop('_args_str', None)
                            # Ensure proper format
                            tc = {
                                'id': tc.get('id'),
                                'name': tc.get('name'),
                                'args': tc.get('args', {}),
                                'type': 'tool_call'
                            }
                        tc_id = tc.get('id')
                        if tc_id and tc_id not in existing_ids:
                            existing_tool_calls_dicts.append(tc)
                            existing_ids.add(tc_id)
                    response.tool_calls = existing_tool_calls_dicts
                    logger.info(f"[AGENT_INVOKE] {self.name} agent: Merged {len(tool_calls_accumulated)} tool calls into response (total: {len(response.tool_calls)}): {[{'name': tc.get('name'), 'args': tc.get('args')} for tc in existing_tool_calls_dicts]}")
            elif final_response and isinstance(final_response, AIMessageChunk):
                # final_response is AIMessageChunk - create new AIMessage with accumulated data
                response = AIMessage(content=accumulated_content)
                if tool_calls_accumulated:
                    # Convert tool calls to dict format and finalize args parsing
                    tool_calls_dicts = []
                    for tc in tool_calls_accumulated:
                        if isinstance(tc, dict):
                            # Finalize args parsing from incremental string if present
                            if '_args_str' in tc and tc['_args_str']:
                                try:
                                    parsed_args = json.loads(tc['_args_str'])
                                    tc['args'] = parsed_args
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.warning(f"[AGENT_INVOKE] {self.name} agent: Failed to parse args string '{tc['_args_str']}': {e}")
                                    tc['args'] = {}
                                # Remove temporary _args_str
                                tc.pop('_args_str', None)
                            tool_calls_dicts.append({
                                'id': tc.get('id'),
                                'name': tc.get('name'),
                                'args': tc.get('args', {}),
                                'type': 'tool_call'
                            })
                        else:
                            # Handle ToolCall object
                            if hasattr(tc, '_args_str') and tc._args_str:
                                try:
                                    parsed_args = json.loads(tc._args_str)
                                    tc.args = parsed_args
                                except (json.JSONDecodeError, ValueError):
                                    tc.args = {}
                            tool_calls_dicts.append({
                                'id': getattr(tc, 'id', None),
                                'name': getattr(tc, 'name', None),
                                'args': getattr(tc, 'args', {}),
                                'type': 'tool_call'
                            })
                    response.tool_calls = tool_calls_dicts
                    logger.info(f"[AGENT_INVOKE] {self.name} agent: Created AIMessage from AIMessageChunk with {len(tool_calls_dicts)} tool calls: {[{'name': tc.get('name'), 'args': tc.get('args')} for tc in tool_calls_dicts]}")
                # Copy metadata from chunk
                if hasattr(final_response, 'response_metadata'):
                    response.response_metadata = final_response.response_metadata
                if hasattr(final_response, 'usage_metadata'):
                    response.usage_metadata = final_response.usage_metadata
            else:
                # Create new AIMessage if we don't have one
                response = AIMessage(content=accumulated_content)
                if tool_calls_accumulated:
                    # Convert tool calls to dict format and finalize args parsing
                    tool_calls_dicts = []
                    for tc in tool_calls_accumulated:
                        if isinstance(tc, dict):
                            # Finalize args parsing from incremental string if present
                            if '_args_str' in tc and tc['_args_str']:
                                try:
                                    parsed_args = json.loads(tc['_args_str'])
                                    tc['args'] = parsed_args
                                except (json.JSONDecodeError, ValueError) as e:
                                    logger.warning(f"[AGENT_INVOKE] {self.name} agent: Failed to parse args string '{tc['_args_str']}': {e}")
                                    tc['args'] = {}
                                # Remove temporary _args_str
                                tc.pop('_args_str', None)
                            tool_calls_dicts.append({
                                'id': tc.get('id'),
                                'name': tc.get('name'),
                                'args': tc.get('args', {}),
                                'type': 'tool_call'
                            })
                        else:
                            # Handle ToolCall object
                            if hasattr(tc, '_args_str') and tc._args_str:
                                try:
                                    parsed_args = json.loads(tc._args_str)
                                    tc.args = parsed_args
                                except (json.JSONDecodeError, ValueError):
                                    tc.args = {}
                            tool_calls_dicts.append({
                                'id': getattr(tc, 'id', None),
                                'name': getattr(tc, 'name', None),
                                'args': getattr(tc, 'args', {}),
                                'type': 'tool_call'
                            })
                    response.tool_calls = tool_calls_dicts
                    logger.info(f"[AGENT_INVOKE] {self.name} agent: Added {len(tool_calls_dicts)} tool calls to new AIMessage: {[{'name': tc.get('name'), 'args': tc.get('args')} for tc in tool_calls_dicts]}")
                # Copy metadata from final_response if available
                if final_response and hasattr(final_response, 'response_metadata'):
                    response.response_metadata = final_response.response_metadata
                if final_response and hasattr(final_response, 'usage_metadata'):
                    response.usage_metadata = final_response.usage_metadata
                    # Log token usage for debugging Langfuse integration
                    if response.usage_metadata:
                        tokens = response.usage_metadata.get('total_tokens', 0) if isinstance(response.usage_metadata, dict) else getattr(response.usage_metadata, 'total_tokens', 0)
                        logger.info(f"[AGENT_INVOKE] {self.name} agent token usage: {tokens} tokens (usage_metadata={response.usage_metadata})")
                    else:
                        logger.warning(f"[AGENT_INVOKE] {self.name} agent: usage_metadata is None or empty")
                else:
                    logger.warning(f"[AGENT_INVOKE] {self.name} agent: final_response has no usage_metadata attribute")
            
            # Log final tool_calls for debugging
            if response.tool_calls:
                logger.info(f"[AGENT_INVOKE] {self.name} agent final response has {len(response.tool_calls)} tool calls: {[tc.get('name') for tc in response.tool_calls]}")
            else:
                logger.debug(f"[AGENT_INVOKE] {self.name} agent final response has no tool calls")
            
            logger.debug(f"[AGENT_INVOKE] {self.name} agent response generated successfully (content_length={len(accumulated_content)})")
            return response
        except Exception as e:
            logger.error(f"Error invoking {self.name} agent: {e}", exc_info=True)
            raise
    
    def stream(self, messages: List[BaseMessage], **kwargs) -> Iterator[BaseMessage]:
        """
        Stream agent response.
        
        Args:
            messages: List of conversation messages
            **kwargs: Additional arguments including config (callbacks, run_id, metadata)
            
        Yields:
            Streaming message chunks
        """
        # Add system prompt
        system_prompt = self.get_system_prompt()
        if system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=system_prompt)] + messages
        
        # Get tools
        tools = self.get_tools()
        
        # Bind tools if available
        if tools:
            llm_with_tools = self.llm.bind_tools(tools)
        else:
            llm_with_tools = self.llm
        
        # Stream response - pass through config from kwargs
        # LangGraph handles callback propagation automatically
        stream_kwargs = {}
        if 'config' in kwargs:
            stream_kwargs['config'] = kwargs['config']
        
        for chunk in llm_with_tools.stream(messages, **stream_kwargs):
            yield chunk
