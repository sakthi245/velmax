# Optional GraphQL API (requires strawberry)
try:
    from .graphql_api import create_app, Query, Mutation, Subscription, scraper_service
    _HAS_GRAPHQL = True
except ImportError:
    _HAS_GRAPHQL = False
    create_app = Query = Mutation = Subscription = scraper_service = None

from .websocket_streaming import (
    MessageType, WSMessage, ConnectionManager, StreamingTaskManager, StreamingScraperService,
    connection_manager, task_manager, streaming_scraper, handle_websocket, handle_message,
    create_task_updates_stream, StreamingScraperService
)

# Define scrape and scrape_async functions inline to avoid circular imports
# These are re-exports from the api module (file)
def scrape(*args, **kwargs):
    """Synchronous scrape function - re-exported from scraper.api module."""
    from ..api import scrape as _scrape
    return _scrape(*args, **kwargs)

async def scrape_async(*args, **kwargs):
    """Asynchronous scrape function - re-exported from scraper.api module."""
    from ..api import scrape_async as _scrape_async
    return await _scrape_async(*args, **kwargs)

__all__ = [
    "MessageType", "WSMessage", "ConnectionManager", "StreamingTaskManager", "StreamingScraperService",
    "connection_manager", "task_manager", "streaming_scraper", "handle_websocket", "handle_message",
    "create_task_updates_stream", "StreamingScraperService",
    "scrape", "scrape_async",
]

if _HAS_GRAPHQL:
    __all__ += [
        "create_app",
        "Query", "Mutation", "Subscription", "scraper_service",
    ]