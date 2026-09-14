from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import strawberry
from strawberry.fastapi import GraphQLRouter
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..engines.interfaces import EngineConfig, EngineMetadata, EngineType, EngineCapability
from ..engines.registry_v2 import EngineRegistryV2
from ..universal_runner import UniversalRunner, UniversalConfig
from ..config.schemas import UniversalRequest, UniversalResult, OutputFormat, EngineType as ConfigEngineType
from ..engines.behavioral_mimicry import BehavioralMimicry, InteractionSequence, InteractionStep, ActionType
from ..engines.ml_extraction import (
    ExtractionSchema, ExtractionResult, ExtractionMethod,
    HybridExtractor, SchemaInferenceEngine, infer_and_extract, extract_with_schema
)


logger = logging.getLogger("graphql_api")


# ============================================================================
# GraphQL Types
# ============================================================================

@strawberry.type
class EngineMetadataType:
    name: str
    engine_type: str
    capabilities: List[str]
    max_concurrent: int
    avg_latency_ms: int
    requires_external_service: bool
    cost_per_1k_pages: float


@strawberry.type
class EngineStatus:
    name: str
    healthy: bool
    last_check: str
    active_tasks: int
    total_tasks: int
    success_rate: float
    avg_latency_ms: float


@strawberry.input
class ScrapeRequestInput:
    url: str
    goal: str = ""
    engine: Optional[str] = None
    engine_options: Dict[str, Any] = field(default_factory=dict)
    max_pages: int = 10
    depth: int = 0
    output_formats: List[str] = field(default_factory=lambda: ["json"])
    use_proxy: bool = False
    render_js: bool = False
    extract_schema: Optional[Dict[str, Any]] = None
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@strawberry.type
class ScrapeResult:
    success: bool
    url: Optional[str] = None
    data: strawberry.scalars.JSON = None
    engine_used: str = ""
    error: Optional[str] = None
    latency_ms: int = 0
    quality_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@strawberry.input
class ExtractionSchemaInput:
    name: str
    description: str = ""
    fields: List["ExtractionFieldInput"] = field(default_factory=list)
    source_url_pattern: Optional[str] = None
    page_type: Optional[str] = None


@strawberry.input
class ExtractionFieldInput:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    selector: Optional[str] = None
    regex: Optional[str] = None
    xpath: Optional[str] = None
    default: Optional[Any] = None
    is_list: bool = False


@strawberry.type
class ExtractionSchemaType:
    name: str
    description: str = ""
    fields: List["ExtractionFieldType"]
    source_url_pattern: Optional[str] = None
    page_type: Optional[str] = None


@strawberry.type
class ExtractionFieldType:
    name: str
    type: str
    description: str = ""
    required: bool = False
    selector: Optional[str] = None
    regex: Optional[str] = None
    xpath: Optional[str] = None
    default: Optional[Any] = None
    is_list: bool = False


@strawberry.type
class ExtractionResultType:
    success: bool
    data: strawberry.scalars.JSON
    method: str
    confidence: float
    errors: List[str]
    warnings: List[str]
    processing_time_ms: int
    tokens_used: int
    cost_estimate: float


@strawberry.input
class InteractionStepInput:
    action: str
    selector: Optional[str] = None
    text: Optional[str] = None
    key: Optional[str] = None
    keys: Optional[List[str]] = None
    x: Optional[int] = None
    y: Optional[int] = None
    delta_x: int = 0
    delta_y: int = 0
    wait_ms: int = 0
    wait_for_selector: Optional[str] = None
    wait_for_function: Optional[str] = None
    wait_for_load_state: Optional[str] = None
    wait_for_navigation: bool = False
    timeout: int = 30000
    options: Dict[str, Any] = field(default_factory=dict)
    stop_on_error: bool = True
    description: str = ""


@strawberry.input
class InteractionSequenceInput:
    steps: List[InteractionStepInput] = field(default_factory=list)
    name: str = ""
    description: str = ""
    stop_on_error: bool = True
    timeout: int = 120000
    retry_failed: bool = False
    max_retries: int = 2


@strawberry.type
class InteractionResultType:
    success: bool
    step_results: List[strawberry.scalars.JSON]
    error: Optional[str] = None
    final_url: str = ""
    elapsed_ms: int = 0


@strawberry.type
class HealthCheck:
    status: str
    timestamp: str
    services: Dict[str, str]
    version: str


# ============================================================================
# WebSocket Manager for Real-time Updates
# ============================================================================

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.task_subscriptions: Dict[str, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"WebSocket connected: {client_id}")
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.task_subscriptions:
            del self.task_subscriptions[client_id]
        logger.info(f"WebSocket disconnected: {client_id}")
    
    async def send_personal_message(self, message: str, client_id: str):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_text(message)
            except Exception as e:
                logger.error(f"Error sending message to {client_id}: {e}")
    
    async def broadcast(self, message: str):
        for client_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_id}: {e}")
    
    def subscribe_to_task(self, client_id: str, task_id: str):
        if client_id not in self.task_subscriptions:
            self.task_subscriptions[client_id] = set()
        self.task_subscriptions[client_id].add(task_id)
    
    async def notify_task_update(self, task_id: str, update: Dict[str, Any]):
        message = json.dumps({
            "type": "task_update",
            "task_id": task_id,
            "data": update,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        for client_id, subscriptions in self.task_subscriptions.items():
            if task_id in subscriptions:
                await self.send_personal_message(message, client_id)


ws_manager = WebSocketManager()


# ============================================================================
# Scraper Service
# ============================================================================

class ScraperService:
    def __init__(self):
        self.config = UniversalConfig()
        self.runner = UniversalRunner(self.config)
        self.extractor = HybridExtractor()
        self.active_tasks: Dict[str, Dict[str, Any]] = {}
    
    async def scrape(self, request: ScrapeRequestInput) -> ScrapeResult:
        """Execute a scrape request."""
        try:
            universal_request = UniversalRequest(
                url=request.url,
                goal=request.goal,
                engine=ConfigEngineType(request.engine) if request.engine else None,
                engine_options=request.engine_options,
                max_pages=request.max_pages,
                depth=request.depth,
                output_formats=[OutputFormat(f) for f in request.output_formats],
                use_proxy=request.use_proxy,
                render_js=request.render_js,
                extract_schema=request.extract_schema,
                priority=request.priority,
                metadata=request.metadata,
            )
            
            result = await self.runner.scrape(universal_request)
            
            return ScrapeResult(
                success=result.success,
                url=result.url,
                data=result.data,
                engine_used=result.engine_used,
                error=result.error,
                latency_ms=result.latency_ms,
                quality_score=result.quality_score,
                metadata=result.metadata or {},
            )
        except Exception as e:
            logger.error(f"Scrape error: {e}")
            return ScrapeResult(
                success=False,
                error=str(e),
            )
    
    async def extract(
        self, 
        html: str, 
        url: str, 
        schema: Optional[ExtractionSchemaInput] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResultType:
        """Extract structured data from HTML."""
        try:
            extraction_schema = None
            if schema:
                extraction_schema = ExtractionSchema(
                    name=schema.name,
                    description=schema.description,
                    fields=[
                        ExtractionField(
                            name=f.name,
                            type=f.type,
                            description=f.description,
                            required=f.required,
                            selector=f.selector,
                            regex=f.regex,
                            xpath=f.xpath,
                            default=f.default,
                            is_list=f.is_list,
                        )
                        for f in schema.fields
                    ],
                    source_url_pattern=schema.source_url_pattern,
                    page_type=schema.page_type,
                )
            
            result = await self.extractor.extract(
                html=html,
                url=url,
                schema=extraction_schema,
                context=context,
            )
            
            return ExtractionResultType(
                success=result.success,
                data=result.data,
                method=result.method.value,
                confidence=result.confidence,
                errors=result.errors,
                warnings=result.warnings,
                processing_time_ms=result.processing_time_ms,
                tokens_used=result.tokens_used,
                cost_estimate=result.cost_estimate,
            )
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return ExtractionResultType(
                success=False,
                data={},
                method="error",
                confidence=0.0,
                errors=[str(e)],
                warnings=[],
                processing_time_ms=0,
                tokens_used=0,
                cost_estimate=0.0,
            )
    
    async def execute_interactions(
        self, 
        sequence: InteractionSequenceInput
    ) -> InteractionResultType:
        """Execute browser interactions with behavioral mimicry."""
        try:
            from playwright.async_api import async_playwright
            
            interaction_seq = InteractionSequence(
                name=sequence.name,
                description=sequence.description,
                stop_on_error=sequence.stop_on_error,
                timeout=sequence.timeout,
                retry_failed=sequence.retry_failed,
                max_retries=sequence.max_retries,
            )
            
            for step_input in sequence.steps:
                step = InteractionStep(
                    action=ActionType(step_input.action),
                    selector=step_input.selector,
                    text=step_input.text,
                    key=step_input.key,
                    keys=step_input.keys,
                    x=step_input.x,
                    y=step_input.y,
                    delta_x=step_input.delta_x,
                    delta_y=step_input.delta_y,
                    wait_ms=step_input.wait_ms,
                    wait_for_selector=step_input.wait_for_selector,
                    wait_for_function=step_input.wait_for_function,
                    wait_for_load_state=step_input.wait_for_load_state,
                    wait_for_navigation=step_input.wait_for_navigation,
                    timeout=step_input.timeout,
                    options=step_input.options,
                    stop_on_error=step_input.stop_on_error,
                    description=step_input.description,
                )
                interaction_seq.add_step(step)
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                
                mimicry = BehavioralMimicry(page)
                result = await mimicry.execute(interaction_seq)
                
                await browser.close()
                
                return InteractionResultType(
                    success=result.success,
                    step_results=[json.loads(json.dumps(r, default=str)) for r in result.step_results],
                    error=result.error,
                    final_url=result.final_url,
                    elapsed_ms=result.elapsed_ms,
                )
                
        except Exception as e:
            logger.error(f"Interaction error: {e}")
            return InteractionResultType(
                success=False,
                step_results=[],
                error=str(e),
                final_url="",
                elapsed_ms=0,
            )


scraper_service = ScraperService()


# ============================================================================
# GraphQL Schema
# ============================================================================

@strawberry.type
class Query:
    @strawberry.field
    async def health(self) -> HealthCheck:
        return HealthCheck(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            services={
                "api": "healthy",
                "runner": "healthy",
                "extractor": "healthy",
            },
            version="0.3.0",
        )
    
    @strawberry.field
    async def engines(self) -> List[EngineMetadataType]:
        engines = []
        for engine_type in EngineType:
            if EngineRegistryV2.is_registered(engine_type):
                meta = EngineRegistryV2.get_metadata(engine_type)
                if meta:
                    engines.append(EngineMetadataType(
                        name=meta.name,
                        engine_type=meta.engine_type.value,
                        capabilities=[c.value for c in meta.capabilities],
                        max_concurrent=meta.max_concurrent,
                        avg_latency_ms=meta.avg_latency_ms,
                        requires_external_service=meta.requires_external_service,
                        cost_per_1k_pages=meta.cost_per_1k_pages,
                    ))
        return engines
    
    @strawberry.field
    async def engine_status(self, name: str) -> Optional[EngineStatus]:
        try:
            engine_type = EngineType(name)
            if not EngineRegistryV2.is_registered(engine_type):
                return None
            
            engine_class = EngineRegistryV2.get(engine_type)
            engine = engine_class()
            
            return EngineStatus(
                name=name,
                healthy=engine.health_check(),
                last_check=datetime.utcnow().isoformat(),
                active_tasks=0,
                total_tasks=0,
                success_rate=1.0,
                avg_latency_ms=0.0,
            )
        except Exception:
            return None
    
    @strawberry.field
    async def infer_schema(self, html: str, url: str = "") -> ExtractionSchemaType:
        inference = SchemaInferenceEngine()
        schema = inference.infer_schema_from_html(html, url)
        
        return ExtractionSchemaType(
            name=schema.name,
            description=schema.description,
            fields=[
                ExtractionFieldType(
                    name=f.name,
                    type=f.type,
                    description=f.description,
                    required=f.required,
                    selector=f.selector,
                    regex=f.regex,
                    xpath=f.xpath,
                    default=f.default,
                    is_list=f.is_list,
                )
                for f in schema.fields
            ],
            source_url_pattern=schema.source_url_pattern,
            page_type=schema.page_type,
        )
    
    @strawberry.field
    async def extract(
        self, 
        html: str, 
        url: str = "", 
        schema: Optional[ExtractionSchemaInput] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResultType:
        return await scraper_service.extract(html, url, schema, context)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def scrape(self, request: ScrapeRequestInput) -> ScrapeResult:
        return await scraper_service.scrape(request)
    
    @strawberry.mutation
    async def extract(
        self, 
        html: str, 
        url: str = "", 
        schema: Optional[ExtractionSchemaInput] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResultType:
        return await scraper_service.extract(html, url, schema, context)
    
    @strawberry.mutation
    async def execute_interactions(self, sequence: InteractionSequenceInput) -> InteractionResultType:
        return await scraper_service.execute_interactions(sequence)
    
    @strawberry.mutation
    async def infer_and_extract(self, html: str, url: str = "") -> ExtractionResultType:
        result = await infer_and_extract(html, url)
        return ExtractionResultType(
            success=result.success,
            data=result.data,
            method=result.method.value,
            confidence=result.confidence,
            errors=result.errors,
            warnings=result.warnings,
            processing_time_ms=result.processing_time_ms,
            tokens_used=result.tokens_used,
            cost_estimate=result.cost_estimate,
        )


# ============================================================================
# WebSocket Subscriptions
# ============================================================================

@strawberry.type
class Subscription:
    @strawberry.subscription
    async def task_updates(self, task_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to task updates via WebSocket."""
        client_id = f"sub_{task_id}_{datetime.utcnow().timestamp()}"
        
        # Create a queue for this subscription
        queue = asyncio.Queue()
        
        async def sender():
            ws = WebSocket(scope={"type": "websocket"}, receive=None, send=None)
            await ws_manager.connect(ws, client_id)
            ws_manager.subscribe_to_task(client_id, task_id)
            
            try:
                while True:
                    data = await queue.get()
                    yield data
            except Exception:
                pass
            finally:
                ws_manager.disconnect(client_id)
        
        # Start sender task
        sender_task = asyncio.create_task(sender())
        
        try:
            # This is a simplified subscription - in production you'd use a proper pub/sub
            while True:
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            sender_task.cancel()


# ============================================================================
# FastAPI App with GraphQL
# ============================================================================

def create_graphql_app() -> FastAPI:
    schema = strawberry.Schema(query=Query, mutation=Mutation, subscription=Subscription)
    graphql_app = GraphQLRouter(schema, path="/graphql")
    
    app = FastAPI(
        title="Hybrid Web Scraper API",
        description="GraphQL API for hybrid web scraping with behavioral mimicry and ML extraction",
        version="0.3.0",
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.include_router(graphql_app, prefix="/api")
    
    # WebSocket endpoint for real-time updates
    @app.websocket("/ws/{client_id}")
    async def websocket_endpoint(websocket: WebSocket, client_id: str):
        await ws_manager.connect(websocket, client_id)
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                if message.get("type") == "subscribe_task":
                    task_id = message.get("task_id")
                    ws_manager.subscribe_to_task(client_id, task_id)
                    await websocket.send_json({"type": "subscribed", "task_id": task_id})
                
                elif message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        
        except WebSocketDisconnect:
            ws_manager.disconnect(client_id)
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            ws_manager.disconnect(client_id)
    
    # REST endpoints for convenience
    @app.post("/api/scrape")
    async def rest_scrape(request: ScrapeRequestInput) -> ScrapeResult:
        return await scraper_service.scrape(request)
    
    @app.post("/api/extract")
    async def rest_extract(
        html: str, 
        url: str = "", 
        schema: Optional[ExtractionSchemaInput] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResultType:
        return await scraper_service.extract(html, url, schema, context)
    
    @app.post("/api/interact")
    async def rest_interact(sequence: InteractionSequenceInput) -> InteractionResultType:
        return await scraper_service.execute_interactions(sequence)
    
    @app.post("/api/infer")
    async def rest_infer(html: str, url: str = "") -> ExtractionSchemaType:
        return await Query().infer_schema(html, url)
    
    @app.post("/api/infer-extract")
    async def rest_infer_extract(html: str, url: str = "") -> ExtractionResultType:
        return await Mutation().infer_and_extract(html, url)
    
    @app.get("/health")
    async def health() -> HealthCheck:
        return await Query().health()
    
    @app.get("/api/engines")
    async def get_engines() -> List[EngineMetadataType]:
        return await Query().engines()
    
    return app


def create_app() -> FastAPI:
    """Factory function to create the FastAPI app with GraphQL."""
    return create_graphql_app()


# For direct execution
if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)