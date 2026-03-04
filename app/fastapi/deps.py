from typing import Optional, Dict, Any
from fastapi import Request
from vanna.core.user.request_context import RequestContext

def context_from_request(request: Request, metadata: Optional[Dict[str, Any]] = None) -> RequestContext:
    """Extract standard Vanna request context from a FastAPI request."""
    return RequestContext(
        cookies=dict(request.cookies),
        headers=dict(request.headers),
        remote_addr=request.client.host if request.client else None,
        query_params=dict(request.query_params),
        metadata=metadata or {},
    )
