from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Set

import aio_pika
from aio_pika import ExchangeType, Message
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractIncomingMessage, AbstractQueue

from ..config import QueueConfig, WorkerConfig
from ..utils.queue import QueueManager, ScrapeTask


@dataclass
class WorkerInfo:
    worker_id: str
    max_concurrent: int
    current_tasks: int = 0
    status: str = "starting"  # starting, healthy, busy, unhealthy, shutting_down
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    capabilities: Dict[str, Any] = field(default_factory=dict)
    metrics_port: int = 9090
    current_tasks_list: List[str] = field(default_factory=list)


class WorkerCoordinator:
    def __init__(
        self,
        queue_manager: QueueManager,
        config: WorkerConfig,
        queue_config: QueueConfig,
    ):
        self.queue_manager = queue_manager
        self.config = config
        self.queue_config = queue_config
        
        self._worker_id = config.worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._connection: Optional[aio_pika.RobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._coordinator_exchange: Optional[aio_pika.abc.AbstractExchange] = None
        self._worker_queue: Optional[aio_pika.abc.AbstractQueue] = None
        
        self._workers: Dict[str, WorkerInfo] = {}
        self._leader_id: Optional[str] = None
        self._is_leader = False
        self._running = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._election_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        
        self._current_tasks: Set[str] = set()
        self._completed_tasks: Set[str] = set()
        self._failed_tasks: Set[str] = set()

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        
        # Connect to RabbitMQ for coordinator communication
        url = f"amqp://{self.queue_config.username}:{self.queue_config.password}@{self.queue_config.host}:{self.queue_config.port}/{self.queue_config.vhost}"
        
        self._connection = await aio_pika.connect_robust(
            f"amqp://{self.queue_config.username}:{self.queue_config.password}@{self.queue_config.host}:{self.queue_config.port}/{self.queue_config.vhost}",
            timeout=self.queue_config.connection_timeout,
            heartbeat=self.queue_config.heartbeat,
        )

        self._channel = await self._connection.channel()
        
        # Declare coordinator exchange
        self._coordinator_exchange = await self._channel.declare_exchange(
            "scrapy.coordinator",
            ExchangeType.TOPIC,
            durable=True,
        )

        # Declare worker-specific queue for commands
        self._worker_queue = await self._channel.declare_queue(
            f"scrapy.worker.{self._worker_id}",
            durable=True,
            auto_delete=True,
        )
        await self._worker_queue.bind(
            self._coordinator_exchange,
            routing_key=f"worker.{self._worker_id}",
        )
        await self._worker_queue.consume(self._on_coordinator_message)

        # Register this worker
        await self._register_worker()

        # Start background tasks
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._election_task = asyncio.create_task(self._leader_election_loop())
        self._monitor_task = asyncio.create_task(self._monitor_workers_loop())

    async def stop(self) -> None:
        self._running = False

        # Cancel background tasks
        for task in [self._heartbeat_task, self._election_task, self._monitor_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Deregister worker
        await self._deregister_worker()

        if self._channel and not self._channel.is_closed:
            await self._channel.close()
        if self._connection and not self._connection.is_closed:
            await self._connection.close()

    async def _register_worker(self) -> None:
        worker_info = WorkerInfo(
            worker_id=self._worker_id,
            max_concurrent=self.config.max_concurrent,
            metrics_port=self.config.metrics_port,
            capabilities={
                "engine": "managed",
                "browser": True,
                "javascript": True,
            },
        )
        
        self._workers[self._worker_id] = worker_info
        
        # Publish registration
        await self._publish_coordinator_event("worker.registered", {
            "worker_id": self._worker_id,
            "max_concurrent": self.config.max_concurrent,
            "metrics_port": self.config.metrics_port,
            "capabilities": worker_info.capabilities,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _deregister_worker(self) -> None:
        await self._publish_coordinator_event("worker.deregistered", {
            "worker_id": self._worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        
        if self._worker_id in self._workers:
            del self._workers[self._worker_id]

    async def _publish_coordinator_event(self, event_type: str, data: Dict[str, Any]) -> None:
        if not self._channel or self._channel.is_closed:
            return

        message = Message(
            json.dumps({
                "event": event_type,
                "worker_id": self._worker_id,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

        try:
            await self._channel.default_exchange.publish(
                message,
                routing_key=f"scrapy.coordinator.{event_type}",
            )
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self._send_heartbeat()
            except Exception:
                pass
            await asyncio.sleep(self.config.heartbeat_interval)

    async def _send_heartbeat(self) -> None:
        if not self._channel or self._channel.is_closed:
            return

        worker = self._workers.get(self._worker_id)
        if not worker:
            return

        worker.last_heartbeat = datetime.now(timezone.utc)
        worker.status = "busy" if worker.current_tasks >= worker.max_concurrent else "healthy"

        await self._publish_coordinator_event("worker.heartbeat", {
            "worker_id": self._worker_id,
            "status": worker.status,
            "current_tasks": worker.current_tasks,
            "max_concurrent": worker.max_concurrent,
            "current_tasks_list": worker.current_tasks_list,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _leader_election_loop(self) -> None:
        while self._running:
            try:
                await self._run_election()
            except Exception:
                pass
            await asyncio.sleep(30)  # Election every 30 seconds

    async def _run_election(self) -> None:
        # Simple leader election: worker with lowest ID becomes leader
        alive_workers = [
            w for w in self._workers.values()
            if (datetime.now(timezone.utc) - w.last_heartbeat).total_seconds() < 90
        ]
        
        if not alive_workers:
            return

        new_leader = min(alive_workers, key=lambda w: w.worker_id)
        
        if new_leader.worker_id != self._leader_id:
            old_leader = self._leader_id
            self._leader_id = new_leader.worker_id
            self._is_leader = (self._leader_id == self._worker_id)
            
            # Notify about leadership change
            await self._publish_coordinator_event("leader.changed", {
                "old_leader": old_leader,
                "new_leader": self._leader_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    async def _monitor_workers_loop(self) -> None:
        while self._running:
            try:
                await self._check_worker_health()
            except Exception:
                pass
            await asyncio.sleep(30)

    async def _check_worker_health(self) -> None:
        now = datetime.now(timezone.utc)
        dead_workers = []
        
        for worker_id, worker in self._workers.items():
            if worker_id == self._worker_id:
                continue
            
            elapsed = (now - worker.last_heartbeat).total_seconds()
            if elapsed > 90:  # 3 missed heartbeats
                dead_workers.append(worker_id)
        
        for dead_id in dead_workers:
            await self._handle_worker_failure(dead_id)

    async def _handle_worker_failure(self, worker_id: str) -> None:
        worker = self._workers.get(worker_id)
        if not worker:
            return

        # Requeue any tasks that were assigned to this worker
        if worker.current_tasks_list:
            # In a real implementation, you'd requeue the specific tasks
            pass

        del self._workers[worker_id]
        
        await self._publish_coordinator_event("worker.failed", {
            "worker_id": worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _on_coordinator_message(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                event = data.get("event")
                
                if event == "worker.registered":
                    await self._handle_worker_registered(data)
                elif event == "worker.deregistered":
                    await self._handle_worker_deregistered(data)
                elif event == "worker.heartbeat":
                    await self._handle_worker_heartbeat(data)
                elif event == "leader.changed":
                    await self._handle_leader_changed(data)
            except Exception:
                pass

    async def _handle_worker_registered(self, data: Dict[str, Any]) -> None:
        worker_id = data.get("worker_id")
        if worker_id == self._worker_id:
            return
        
        worker = WorkerInfo(
            worker_id=worker_id,
            max_concurrent=data.get("max_concurrent", 5),
            metrics_port=data.get("metrics_port", 9090),
            capabilities=data.get("capabilities", {}),
        )
        self._workers[worker_id] = worker

    async def _handle_worker_deregistered(self, data: Dict[str, Any]) -> None:
        worker_id = data.get("worker_id")
        if worker_id in self._workers:
            del self._workers[worker_id]

    async def _handle_worker_heartbeat(self, data: Dict[str, Any]) -> None:
        worker_id = data.get("worker_id")
        if worker_id not in self._workers:
            return

        worker = self._workers[worker_id]
        worker.last_heartbeat = datetime.now(timezone.utc)
        worker.status = data.get("status", "healthy")
        worker.current_tasks = data.get("current_tasks", 0)
        worker.current_tasks_list = data.get("current_tasks_list", [])

    async def _handle_leader_changed(self, data: Dict[str, Any]) -> None:
        self._leader_id = data.get("new_leader")
        self._is_leader = (self._leader_id == self._worker_id)

    def register_task(self, task_id: str) -> bool:
        """Register a task as being processed by this worker."""
        if self._worker_id not in self._workers:
            return False
        
        worker = self._workers[self._worker_id]
        if worker.current_tasks >= worker.max_concurrent:
            return False
        
        worker.current_tasks += 1
        worker.current_tasks_list.append(task_id)
        self._current_tasks.add(task_id)
        return True

    def complete_task(self, task_id: str, success: bool = True) -> None:
        """Mark a task as completed."""
        if task_id in self._current_tasks:
            self._current_tasks.discard(task_id)
        
        if self._worker_id in self._workers:
            worker = self._workers[self._worker_id]
            worker.current_tasks = max(0, worker.current_tasks - 1)
            if task_id in worker.current_tasks_list:
                worker.current_tasks_list.remove(task_id)
        
        if success:
            self._completed_tasks.add(task_id)
        else:
            self._failed_tasks.add(task_id)

    def get_cluster_stats(self) -> Dict[str, Any]:
        total_workers = len(self._workers)
        healthy_workers = sum(1 for w in self._workers.values() if w.status == "healthy")
        busy_workers = sum(1 for w in self._workers.values() if w.status == "busy")
        total_tasks = sum(w.current_tasks for w in self._workers.values())
        max_capacity = sum(w.max_concurrent for w in self._workers.values())

        return {
            "worker_id": self._worker_id,
            "is_leader": self._is_leader,
            "leader_id": self._leader_id,
            "total_workers": total_workers,
            "healthy_workers": healthy_workers,
            "busy_workers": busy_workers,
            "total_tasks": total_tasks,
            "max_capacity": max_capacity,
            "capacity_utilization": total_tasks / max_capacity if max_capacity > 0 else 0,
            "my_status": self._workers.get(self._worker_id, WorkerInfo(worker_id="")).status,
            "my_current_tasks": self._workers.get(self._worker_id, WorkerInfo(worker_id="")).current_tasks,
        }

    def get_worker_info(self, worker_id: str) -> Optional[WorkerInfo]:
        return self._workers.get(worker_id)

    def get_all_workers(self) -> List[WorkerInfo]:
        return list(self._workers.values())


@asynccontextmanager
async def create_coordinator(
    queue_manager: QueueManager,
    worker_config: WorkerConfig,
    queue_config: QueueConfig,
) -> AsyncIterator[WorkerCoordinator]:
    coordinator = WorkerCoordinator(queue_manager, worker_config, queue_config)
    try:
        await coordinator.start()
        yield coordinator
    finally:
        await coordinator.stop()