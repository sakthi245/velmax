from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Set
from contextlib import asynccontextmanager

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState


logger = logging.getLogger("websocket_streaming")


class MessageType(Enum):
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    TASK_UPDATE = "task_update"
    TASK_COMPLETE = "task_complete"
    TASK_ERROR = "task_error"
    PROGRESS = "progress"
    LOG = "log"
    METRIC = "metric"
    PING = "ping"
    PONG = "pong"
    ERROR = "error"


@dataclass
class WSMessage:
    type: MessageType
    payload: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_json(self) -> str:
        return json.dumps({
            "type": self.type.value,
            "payload": self.payload,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> "WSMessage":
        data = json.loads(json_str)
        return cls(
            type=MessageType(data["type"]),
            payload=data.get("payload", {}),
            request_id=data.get("request_id"),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
        )


class ConnectionManager:
    """Manages WebSocket connections and subscriptions."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # client_id -> set of topics
        self.topic_subscribers: Dict[str, Set[str]] = {}  # topic -> set of client_ids
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger("connection_manager")
    
    async def connect(self, websocket: WebSocket, client_id: Optional[str] = None) -> str:
        if client_id is None:
            client_id = str(uuid.uuid4())
        
        await websocket.accept()
        
        async with self._lock:
            self.active_connections[client_id] = websocket
            self.connection_metadata[client_id] = {
                "connected_at": datetime.utcnow().isoformat(),
                "subscriptions": set(),
                "last_ping": datetime.utcnow().isoformat(),
            }
            self.subscriptions[client_id] = set()
        
        self.logger.info(f"Client connected: {client_id} (total: {len(self.active_connections)})")
        return client_id
    
    async def disconnect(self, client_id: str):
        async with self._lock:
            if client_id in self.active_connections:
                del self.active_connections[client_id]
            
            if client_id in self.connection_metadata:
                del self.connection_metadata[client_id]
            
            # Clean up subscriptions
            if client_id in self.subscriptions:
                for topic in self.subscriptions[client_id]:
                    if topic in self.topic_subscribers:
                        self.topic_subscribers[topic].discard(client_id)
                        if not self.topic_subscribers[topic]:
                            del self.topic_subscribers[topic]
                del self.subscriptions[client_id]
        
        self.logger.info(f"Client disconnected: {client_id} (total: {len(self.active_connections)})")
    
    async def subscribe(self, client_id: str, topic: str) -> bool:
        async with self._lock:
            if client_id not in self.active_connections:
                return False
            
            if client_id not in self.subscriptions:
                self.subscriptions[client_id] = set()
            
            self.subscriptions[client_id].add(topic)
            self.connection_metadata[client_id]["subscriptions"].add(topic)
            
            if topic not in self.topic_subscribers:
                self.topic_subscribers[topic] = set()
            self.topic_subscribers[topic].add(client_id)
            
            return True
    
    async def unsubscribe(self, client_id: str, topic: str) -> bool:
        async with self._lock:
            if client_id not in self.subscriptions:
                return False
            
            if topic in self.subscriptions[client_id]:
                self.subscriptions[client_id].discard(topic)
                self.connection_metadata[client_id]["subscriptions"].discard(topic)
                
                if topic in self.topic_subscribers:
                    self.topic_subscribers[topic].discard(client_id)
                    if not self.topic_subscribers[topic]:
                        del self.topic_subscribers[topic]
                
                return True
            
            return False
    
    async def send_personal_message(self, message: WSMessage, client_id: str) -> bool:
        async with self._lock:
            websocket = self.active_connections.get(client_id)
            if not websocket or websocket.client_state != WebSocketState.CONNECTED:
                return False
            
            try:
                await websocket.send_text(message.to_json())
                return True
            except Exception as e:
                self.logger.error(f"Error sending to {client_id}: {e}")
                return False
    
    async def broadcast_to_topic(self, message: WSMessage, topic: str) -> int:
        sent_count = 0
        async with self._lock:
            subscribers = self.topic_subscribers.get(topic, set()).copy()
        
        for client_id in subscribers:
            if await self.send_personal_message(message, client_id):
                sent_count += 1
        
        return sent_count
    
    async def broadcast(self, message: WSMessage) -> int:
        sent_count = 0
        async with self._lock:
            client_ids = list(self.active_connections.keys())
        
        for client_id in client_ids:
            if await self.send_personal_message(message, client_id):
                sent_count += 1
        
        return sent_count
    
    def get_connection_info(self, client_id: str) -> Optional[Dict[str, Any]]:
        return self.connection_metadata.get(client_id)
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_connections": len(self.active_connections),
            "total_subscriptions": sum(len(s) for s in self.subscriptions.values()),
            "topics": {topic: len(subs) for topic, subs in self.topic_subscribers.items()},
        }


class StreamingTaskManager:
    """Manages long-running tasks with real-time streaming updates."""
    
    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
        self.task_results: Dict[str, Any] = {}
        self.logger = logging.getLogger("streaming_task_manager")
    
    async def create_task(
        self,
        task_id: str,
        task_type: str,
        params: Dict[str, Any],
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new streaming task."""
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "params": params,
            "client_id": client_id,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "started_at": None,
            "completed_at": None,
            "progress": 0.0,
            "current_step": "",
            "logs": [],
            "metrics": {},
            "result": None,
            "error": None,
        }
        
        self.active_tasks[task_id] = task
        
        # Subscribe client to task updates
        if client_id:
            await self.connection_manager.subscribe(client_id, f"task:{task_id}")
            await self.connection_manager.subscribe(client_id, "tasks")
        
        # Notify task created
        await self._notify_task_update(task_id, {
            "status": "created",
            "progress": 0.0,
        })
        
        return task
    
    async def start_task(self, task_id: str):
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task["status"] = "running"
            task["started_at"] = datetime.utcnow().isoformat()
            await self._notify_task_update(task_id, {"status": "running", "progress": 0.0})
    
    async def update_progress(
        self, 
        task_id: str, 
        progress: float, 
        current_step: str = "",
        metrics: Optional[Dict[str, Any]] = None,
    ):
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task["progress"] = max(0.0, min(1.0, progress))
            task["current_step"] = current_step
            if metrics:
                task["metrics"].update(metrics)
            
            await self._notify_task_update(task_id, {
                "status": "running",
                "progress": task["progress"],
                "current_step": current_step,
                "metrics": metrics or {},
            })
    
    async def add_log(self, task_id: str, level: str, message: str, data: Optional[Dict[str, Any]] = None):
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "level": level,
                "message": message,
                "data": data,
            }
            task["logs"].append(log_entry)
            
            # Keep only last 1000 logs
            if len(task["logs"]) > 1000:
                task["logs"] = task["logs"][-1000:]
            
            await self.connection_manager.broadcast_to_topic(
                WSMessage(
                    type=MessageType.LOG,
                    payload={
                        "task_id": task_id,
                        "log": log_entry,
                    },
                ),
                f"task:{task_id}",
            )
    
    async def complete_task(self, task_id: str, result: Any = None):
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task["status"] = "completed"
            task["completed_at"] = datetime.utcnow().isoformat()
            task["progress"] = 1.0
            task["result"] = result
            
            self.task_results[task_id] = result
            
            await self._notify_task_update(task_id, {
                "status": "completed",
                "progress": 1.0,
                "result": result,
            })
            
            # Move to results after a delay
            asyncio.create_task(self._archive_task(task_id))
    
    async def fail_task(self, task_id: str, error: str):
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task["status"] = "failed"
            task["completed_at"] = datetime.utcnow().isoformat()
            task["error"] = error
            
            await self._notify_task_update(task_id, {
                "status": "failed",
                "progress": task["progress"],
                "error": error,
            })
    
    async def _notify_task_update(self, task_id: str, update: Dict[str, Any]):
        message = WSMessage(
            type=MessageType.TASK_UPDATE,
            payload={
                "task_id": task_id,
                **update,
            },
        )
        
        await self.connection_manager.broadcast_to_topic(message, f"task:{task_id}")
        await self.connection_manager.broadcast_to_topic(message, "tasks")
    
    async def _archive_task(self, task_id: str, delay: int = 300):
        await asyncio.sleep(delay)
        if task_id in self.active_tasks:
            del self.active_tasks[task_id]
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self.active_tasks.get(task_id) or self.task_results.get(task_id)
    
    def list_tasks(self, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = list(self.active_tasks.values())
        if client_id:
            tasks = [t for t in tasks if t.get("client_id") == client_id]
        return tasks


class StreamingScraperService:
    """Streaming version of the scraper service with real-time updates."""
    
    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
        self.task_manager = StreamingTaskManager(connection_manager)
        self.logger = logging.getLogger("streaming_scraper")
    
    async def scrape_with_streaming(
        self,
        task_id: str,
        url: str,
        goal: str = "",
        engine: Optional[str] = None,
        engine_options: Optional[Dict[str, Any]] = None,
        max_pages: int = 10,
        depth: int = 0,
        output_formats: List[str] = None,
        use_proxy: bool = False,
        render_js: bool = False,
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a scraping task with real-time streaming updates."""
        # Create task
        task = await self.task_manager.create_task(
            task_id=task_id,
            task_type="scrape",
            params={
                "url": url,
                "goal": goal,
                "engine": engine,
                "engine_options": engine_options or {},
                "max_pages": max_pages,
                "depth": depth,
                "output_formats": output_formats or ["json"],
                "use_proxy": use_proxy,
                "render_js": render_js,
            },
            client_id=client_id,
        )
        
        # Start the actual scraping in background
        asyncio.create_task(self._run_scrape(task_id, url, goal, engine, engine_options, max_pages, depth, output_formats, use_proxy, render_js))
        
        return {"task_id": task_id, "status": "started"}
    
    async def _run_scrape(
        self,
        task_id: str,
        url: str,
        goal: str,
        engine: Optional[str],
        engine_options: Optional[Dict[str, Any]],
        max_pages: int,
        depth: int,
        output_formats: List[str],
        use_proxy: bool,
        render_js: bool,
    ):
        from ..universal_runner import UniversalRunner, UniversalConfig
        from ..config.schemas import UniversalRequest, OutputFormat, EngineType as ConfigEngineType
        
        try:
            await self.task_manager.start_task(task_id)
            await self.task_manager.add_log(task_id, "info", f"Starting scrape of {url}")
            await self.task_manager.update_progress(task_id, 0.1, "Initializing scraper")
            
            # Create runner
            config = UniversalConfig()
            runner = UniversalRunner(config)
            
            request = UniversalRequest(
                url=url,
                goal=goal,
                engine=ConfigEngineType(engine) if engine else None,
                engine_options=engine_options or {},
                max_pages=max_pages,
                depth=depth,
                output_formats=[OutputFormat(f) for f in (output_formats or ["json"])],
                use_proxy=use_proxy,
                render_js=render_js,
            )
            
            await self.task_manager.update_progress(task_id, 0.3, "Running scraper")
            await self.task_manager.add_log(task_id, "info", "Running universal runner")
            
            result = await runner.scrape(request)
            
            await self.task_manager.update_progress(task_id, 0.9, "Processing results")
            await self.task_manager.add_log(task_id, "info", "Scraping completed successfully")
            
            await self.task_manager.complete_task(task_id, {
                "success": result.success,
                "url": result.url,
                "data": result.data,
                "engine_used": result.engine_used,
                "latency_ms": result.latency_ms,
                "quality_score": result.quality_score,
            })
            
        except Exception as e:
            self.logger.error(f"Scrape error for task {task_id}: {e}")
            await self.task_manager.add_log(task_id, "error", f"Scrape failed: {str(e)}")
            await self.task_manager.fail_task(task_id, str(e))


# Global instances
connection_manager = ConnectionManager()
task_manager = StreamingTaskManager(connection_manager)
streaming_scraper = StreamingScraperService(connection_manager)


# WebSocket endpoint handler
async def handle_websocket(websocket: WebSocket, client_id: Optional[str] = None):
    """Handle WebSocket connection with full protocol support."""
    if client_id is None:
        client_id = str(uuid.uuid4())
    
    client_id = await connection_manager.connect(websocket, client_id)
    
    try:
        # Send welcome message
        await connection_manager.send_personal_message(
            WSMessage(
                type=MessageType.CONNECT,
                payload={
                    "client_id": client_id,
                    "message": "Connected to Hybrid Scraper streaming service",
                    "server_time": datetime.utcnow().isoformat(),
                },
            ),
            client_id,
        )
        
        while True:
            try:
                data = await websocket.receive_text()
                message = WSMessage.from_json(data)
                
                await handle_message(client_id, message)
                
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await connection_manager.send_personal_message(
                    WSMessage(
                        type=MessageType.ERROR,
                        payload={"error": "Invalid JSON"},
                    ),
                    client_id,
                )
            except Exception as e:
                logger.error(f"WebSocket error for {client_id}: {e}")
                await connection_manager.send_personal_message(
                    WSMessage(
                        type=MessageType.ERROR,
                        payload={"error": str(e)},
                    ),
                    client_id,
                )
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
    finally:
        connection_manager.disconnect(client_id)


async def handle_message(client_id: str, message: WSMessage):
    """Handle incoming WebSocket messages."""
    try:
        if message.type == MessageType.PING:
            await connection_manager.send_personal_message(
                WSMessage(type=MessageType.PONG, request_id=message.request_id),
                client_id,
            )
        
        elif message.type == MessageType.SUBSCRIBE:
            topic = message.payload.get("topic")
            if topic:
                await connection_manager.subscribe(client_id, topic)
                await connection_manager.send_personal_message(
                    WSMessage(
                        type=MessageType.SUBSCRIBE,
                        payload={"topic": topic, "status": "subscribed"},
                        request_id=message.request_id,
                    ),
                    client_id,
                )
        
        elif message.type == MessageType.UNSUBSCRIBE:
            topic = message.payload.get("topic")
            if topic:
                await connection_manager.unsubscribe(client_id, topic)
                await connection_manager.send_personal_message(
                    WSMessage(
                        type=MessageType.UNSUBSCRIBE,
                        payload={"topic": topic, "status": "unsubscribed"},
                        request_id=message.request_id,
                    ),
                    client_id,
                )
        
        elif message.type == MessageType.TASK_UPDATE:
            # Client requesting task update
            task_id = message.payload.get("task_id")
            if task_id:
                task_manager = StreamingTaskManager(connection_manager)
                task = task_manager.get_task(task_id)
                if task:
                    await connection_manager.send_personal_message(
                        WSMessage(
                            type=MessageType.TASK_UPDATE,
                            payload={"task": task},
                            request_id=message.request_id,
                        ),
                        client_id,
                    )
                else:
                    await connection_manager.send_personal_message(
                        WSMessage(
                            type=MessageType.ERROR,
                            payload={"error": "Task not found"},
                            request_id=message.request_id,
                        ),
                        client_id,
                    )
    
    except Exception as e:
        logger.error(f"Error handling message from {client_id}: {e}")
        await connection_manager.send_personal_message(
            WSMessage(
                type=MessageType.ERROR,
                payload={"error": f"Handler error: {str(e)}"},
                request_id=message.request_id,
            ),
            client_id,
        )


# FastAPI WebSocket endpoint
async def websocket_endpoint(websocket: WebSocket, client_id: Optional[str] = None):
    await handle_websocket(websocket, client_id)


# Task streaming endpoints
async def create_scrape_task(
    url: str,
    goal: str = "",
    engine: Optional[str] = None,
    engine_options: Optional[Dict[str, Any]] = None,
    max_pages: int = 10,
    depth: int = 0,
    output_formats: List[str] = None,
    use_proxy: bool = False,
    render_js: bool = False,
    client_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new scraping task with streaming updates."""
    task_id = str(uuid.uuid4())
    
    result = await streaming_scraper.scrape_with_streaming(
        task_id=task_id,
        url=url,
        goal=goal,
        engine=engine,
        engine_options=engine_options,
        max_pages=max_pages,
        depth=depth,
        output_formats=output_formats or ["json"],
        use_proxy=use_proxy,
        render_js=render_js,
        client_id=client_id,
    )
    
    return result


async def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """Get current task status."""
    return task_manager.get_task(task_id)


async def list_tasks(client_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all tasks."""
    return task_manager.list_tasks(client_id)


async def subscribe_to_task(websocket: WebSocket, task_id: str, client_id: str):
    """Subscribe to task updates via WebSocket."""
    await connection_manager.connect(websocket, client_id)
    await connection_manager.subscribe(client_id, f"task:{task_id}")
    await connection_manager.subscribe(client_id, "tasks")
    
    try:
        # Send current task status
        task = task_manager.get_task(task_id)
        if task:
            await websocket.send_text(json.dumps({
                "type": "task_status",
                "payload": task,
            }))
        
        # Keep connection alive and forward updates
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        connection_manager.disconnect(client_id)


# Utility functions
async def create_task_updates_stream(task_id: str) -> AsyncGenerator[Dict[str, Any], None]:
    """Create an async generator for task updates (for Server-Sent Events)."""
    queue = asyncio.Queue()
    
    async def listener():
        # This would be connected to the actual task manager in production
        pass
    
    asyncio.create_task(listener())
    
    while True:
        update = await queue.get()
        yield update