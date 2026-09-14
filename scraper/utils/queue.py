from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

import aio_pika
from aio_pika import ExchangeType, Message, RobustConnection, RobustQueue
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractIncomingMessage, AbstractQueue

from ..config import QueueConfig, TaskPriority, WorkerConfig
from ..config.schemas import UniversalConfig


@dataclass
class ScrapeTask:
    task_id: str
    url: str
    priority: TaskPriority = TaskPriority.OTHER
    depth: int = 0
    retry_count: int = 0
    max_retries: int = 3
    session_id: str = ""
    engine: str = "managed"
    goal: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scheduled_at: Optional[datetime] = None

    def to_json(self) -> str:
        return json.dumps({
            "task_id": self.task_id,
            "url": self.url,
            "priority": self.priority.value,
            "depth": self.depth,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "session_id": self.session_id,
            "engine": self.engine,
            "goal": self.goal,
            "schema": self.schema,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
        })

    @classmethod
    def from_json(cls, data: str) -> "ScrapeTask":
        d = json.loads(data)
        return cls(
            task_id=d["task_id"],
            url=d["url"],
            priority=TaskPriority(d.get("priority", "other")),
            depth=d.get("depth", 0),
            retry_count=d.get("retry_count", 0),
            max_retries=d.get("max_retries", 3),
            session_id=d.get("session_id", ""),
            engine=d.get("engine", "managed"),
            goal=d.get("goal", ""),
            schema=d.get("schema", {}),
            metadata=d.get("metadata", {}),
            created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(timezone.utc),
            scheduled_at=datetime.fromisoformat(d["scheduled_at"]) if d.get("scheduled_at") else None,
        )

    def routing_key(self) -> str:
        return f"task.{self.priority.value}"


class QueueManager:
    def __init__(self, config: QueueConfig):
        self.config = config
        self._connection: Optional[RobustConnection] = None
        self._channel: Optional[AbstractChannel] = None
        self._priority_exchange: Optional[AbstractExchange] = None
        self._dlx_exchange: Optional[AbstractExchange] = None
        self._queues: Dict[TaskPriority, AbstractQueue] = {}
        self._dlq: Optional[AbstractQueue] = None
        self._consumer_tags: Dict[str, str] = {}
        self._running = False
        self._message_handlers: List[Callable[[ScrapeTask], Any]] = []
        self._task_queue: asyncio.Queue = asyncio.Queue()

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def connect(self) -> None:
        if self.is_connected:
            return

        url = f"amqp://{self.config.username}:{self.config.password}@{self.config.host}:{self.config.port}/{self.config.vhost}"
        
        self._connection = await aio_pika.connect_robust(
            url,
            timeout=self.config.connection_timeout,
            heartbeat=self.config.heartbeat,
        )

        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=self.config.prefetch_count)

        if self.config.publisher_confirms:
            # aio_pika 10+ uses property instead of method
            if hasattr(self._channel, 'enable_publisher_confirms'):
                await self._channel.enable_publisher_confirms()
            else:
                # Newer versions use publisher_confirms property
                self._channel.publisher_confirms = True

        # Declare exchanges
        self._priority_exchange = await self._channel.declare_exchange(
            self.config.priority_exchange,
            ExchangeType.TOPIC,
            durable=True,
        )

        self._dlx_exchange = await self._channel.declare_exchange(
            self.config.dead_letter_exchange,
            ExchangeType.FANOUT,
            durable=True,
        )

        # Declare priority queues
        for priority in TaskPriority:
            queue_name = f"scrapy.tasks.{priority.value}"
            queue = await self._channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": self.config.dead_letter_exchange,
                    "x-dead-letter-routing-key": "dead",
                    "x-max-priority": 10,
                },
            )
            await queue.bind(self._priority_exchange, routing_key=f"task.{priority.value}")
            self._queues[priority] = queue

        # Declare dead letter queue
        self._dlq = await self._channel.declare_queue(
            "scrapy.dlq",
            durable=True,
        )
        await self._dlq.bind(self._dlx_exchange, routing_key="dead")

        # Set up consumer callbacks
        for priority in TaskPriority:
            queue = self._queues[priority]
            await queue.consume(self._on_message, no_ack=False)

    async def close(self) -> None:
        self._running = False
        for tag in self._consumer_tags.values():
            if self._channel:
                try:
                    await self._channel.basic_cancel(tag)
                except Exception:
                    pass
        self._consumer_tags.clear()
        
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()

    async def publish_task(self, task: ScrapeTask) -> bool:
        if not self.is_connected:
            await self.connect()

        message = Message(
            task.to_json().encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            priority=self._priority_value(task.priority),
            message_id=task.task_id,
            timestamp=task.created_at,
            headers={
                "task_id": task.task_id,
                "session_id": task.session_id,
                "retry_count": str(task.retry_count),
                "max_retries": str(task.max_retries),
                "engine": task.engine,
            },
        )

        try:
            await self._priority_exchange.publish(
                message,
                routing_key=task.routing_key(),
                mandatory=True,
            )
            return True
        except Exception:
            return False

    async def publish_tasks(self, tasks: List[ScrapeTask]) -> int:
        count = 0
        for task in tasks:
            if await self.publish_task(task):
                count += 1
        return count

    async def requeue_task(self, task: ScrapeTask, delay: float = 0) -> bool:
        """Requeue a task with optional delay."""
        if delay > 0:
            await asyncio.sleep(delay)
        task.retry_count += 1
        return await self.publish_task(task)

    async def send_to_dlq(self, task: ScrapeTask, error: str) -> bool:
        """Send task to dead letter queue."""
        if not self.is_connected:
            return False

        message = Message(
            task.to_json().encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            priority=0,
            message_id=f"dlq-{task.task_id}",
            timestamp=datetime.now(timezone.utc),
            headers={
                "task_id": task.task_id,
                "session_id": task.session_id,
                "retry_count": str(task.retry_count),
                "max_retries": str(task.max_retries),
                "engine": task.engine,
                "error": error,
                "original_priority": task.priority.value,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        try:
            await self._dlx_exchange.publish(
                message,
                routing_key="dead",
            )
            return True
        except Exception:
            return False

    def register_handler(self, handler: Callable[[ScrapeTask], Any]) -> None:
        self._message_handlers.append(handler)

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        async with message.process():
            try:
                task = ScrapeTask.from_json(message.body.decode())
                
                # Put task in internal queue for workers to retrieve
                await self._task_queue.put(task)
                
                for handler in self._message_handlers:
                    try:
                        await handler(task)
                    except Exception as e:
                        # Log error but continue with other handlers
                        pass
            except Exception:
                # If we can't parse, reject without requeue
                pass

    def _priority_value(self, priority: TaskPriority) -> int:
        mapping = {
            TaskPriority.DETAIL: 10,
            TaskPriority.LIST: 5,
            TaskPriority.OTHER: 1,
        }
        return mapping.get(priority, 1)

    async def get_tasks(self, batch_size: int = 10) -> List[ScrapeTask]:
        """Get tasks from internal queue."""
        tasks = []
        for _ in range(batch_size):
            try:
                task = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
                tasks.append(task)
            except asyncio.TimeoutError:
                break
        return tasks

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        if not self.is_connected:
            return {}

        stats = {}
        for priority, queue in self._queues.items():
            try:
                declare_ok = await queue.declare(passive=True)
                stats[priority.value] = {
                    "message_count": declare_ok.message_count,
                    "consumer_count": declare_ok.consumer_count,
                }
            except Exception:
                stats[priority.value] = {"error": "Failed to get stats"}

        if self._dlq:
            try:
                declare_ok = await self._dlq.declare(passive=True)
                stats["dlq"] = {
                    "message_count": declare_ok.message_count,
                    "consumer_count": declare_ok.consumer_count,
                }
            except Exception:
                stats["dlq"] = {"error": "Failed to get stats"}

        return stats


@asynccontextmanager
async def create_queue_manager(config: QueueConfig) -> AsyncIterator[QueueManager]:
    manager = QueueManager(config)
    try:
        await manager.connect()
        yield manager
    finally:
        await manager.close()


class TaskScheduler:
    def __init__(self, queue_manager: QueueManager, config: UniversalConfig):
        self.queue_manager = queue_manager
        self.config = config
        self._pending_tasks: List[ScrapeTask] = []
        self._running = False

    async def add_task(self, task: ScrapeTask) -> None:
        self._pending_tasks.append(task)
        # Sort by priority (highest first)
        self._pending_tasks.sort(key=lambda t: self._priority_value(t.priority), reverse=True)

    async def add_tasks(self, tasks: List[ScrapeTask]) -> None:
        self._pending_tasks.extend(tasks)
        self._pending_tasks.sort(key=lambda t: self._priority_value(t.priority), reverse=True)

    async def flush(self, batch_size: int = 100) -> int:
        """Publish pending tasks in batches."""
        if not self._pending_tasks:
            return 0

        batch = self._pending_tasks[:batch_size]
        self._pending_tasks = self._pending_tasks[batch_size:]
        return await self.queue_manager.publish_tasks(batch)

    async def flush_all(self) -> int:
        total = 0
        while self._pending_tasks:
            total += await self.flush()
        return total

    def _priority_value(self, priority: TaskPriority) -> int:
        mapping = {
            TaskPriority.DETAIL: 10,
            TaskPriority.LIST: 5,
            TaskPriority.OTHER: 1,
        }
        return mapping.get(priority, 1)

    def pending_count(self) -> int:
        return len(self._pending_tasks)

    def clear(self) -> None:
        self._pending_tasks.clear()


async def create_task_from_url(
    url: str,
    session_id: str,
    goal: str = "",
    schema: Optional[Dict[str, Any]] = None,
    engine: str = "managed",
    priority: TaskPriority = TaskPriority.OTHER,
    depth: int = 0,
    max_retries: int = 3,
) -> ScrapeTask:
    return ScrapeTask(
        task_id=str(uuid.uuid4())[:16],
        url=url,
        priority=priority,
        depth=depth,
        session_id=session_id,
        engine=engine,
        goal=goal,
        schema=schema or {},
        max_retries=max_retries,
    )