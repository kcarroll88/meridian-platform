import uuid
import time
import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class TraceMiddleware(BaseHTTPMiddleware):
    """Attaches a trace_id to every request for end-to-end observability."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        start = time.monotonic()

        # Bind trace context for all log lines in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)

        latency_ms = int((time.monotonic() - start) * 1000)
        structlog.contextvars.bind_contextvars(
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        structlog.get_logger().info("request_completed")

        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Latency-Ms"] = str(latency_ms)
        return response
