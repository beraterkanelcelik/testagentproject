"""
Distributed tracing middleware using OpenTelemetry.
"""
from typing import Callable
from django.http import HttpRequest, HttpResponse
from app.core.logging import get_logger

logger = get_logger(__name__)


def tracing_middleware(get_response: Callable) -> Callable:
    """
    OpenTelemetry tracing middleware for Django.
    
    Adds distributed tracing context to requests.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.propagate import extract
        from opentelemetry.trace import Status, StatusCode
        
        tracer = trace.get_tracer(__name__)
    except ImportError:
        logger.warning("OpenTelemetry not installed, tracing middleware disabled")
        tracer = None
    
    def middleware(request: HttpRequest) -> HttpResponse:
        if not tracer:
            return get_response(request)
        
        # Extract trace context from headers
        context = extract(request.headers)
        
        # Start span
        with tracer.start_as_current_span(
            f"{request.method} {request.path}",
            context=context
        ) as span:
            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", request.get_full_path())
            span.set_attribute("http.user_agent", request.META.get("HTTP_USER_AGENT", ""))
            
            try:
                response = get_response(request)
                span.set_attribute("http.status_code", response.status_code)
                
                if response.status_code >= 400:
                    span.set_status(Status(StatusCode.ERROR))
                
                return response
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise
    
    return middleware
