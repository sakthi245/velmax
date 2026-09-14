from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable, Tuple
from playwright.async_api import Page, Locator, TimeoutError as PlaywrightTimeoutError


class ActionType(Enum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    HOVER = "hover"
    FILL = "fill"
    TYPE = "type"
    PRESS = "press"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    FOCUS = "focus"
    BLUR = "blur"
    SCROLL = "scroll"
    SCROLL_INTO_VIEW = "scroll_into_view"
    WAIT = "wait"
    WAIT_FOR_SELECTOR = "wait_for_selector"
    WAIT_FOR_FUNCTION = "wait_for_function"
    WAIT_FOR_LOAD_STATE = "wait_for_load_state"
    WAIT_FOR_NAVIGATION = "wait_for_navigation"
    EVALUATE = "evaluate"
    SCREENSHOT = "screenshot"
    DRAG_AND_DROP = "drag_and_drop"
    FILE_UPLOAD = "file_upload"
    CLEAR = "clear"
    KEYBOARD = "keyboard"
    MOUSE_MOVE = "mouse_move"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    # New human-like actions
    MOUSE_JITTER = "mouse_jitter"
    READING_PAUSE = "reading_pause"
    RANDOM_MOUSE_MOVE = "random_mouse_move"
    # Pagination-specific actions
    PAGINATION_CLICK = "pagination_click"


@dataclass
class InteractionStep:
    action: ActionType
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
    timeout: int = 60000
    options: Dict[str, Any] = field(default_factory=dict)
    stop_on_error: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "selector": self.selector,
            "text": self.text,
            "key": self.key,
            "keys": self.keys,
            "x": self.x,
            "y": self.y,
            "delta_x": self.delta_x,
            "delta_y": self.delta_y,
            "wait_ms": self.wait_ms,
            "wait_for_selector": self.wait_for_selector,
            "wait_for_function": self.wait_for_function,
            "wait_for_load_state": self.wait_for_load_state,
            "wait_for_navigation": self.wait_for_navigation,
            "timeout": self.timeout,
            "options": self.options,
            "stop_on_error": self.stop_on_error,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractionStep":
        data["action"] = ActionType(data["action"])
        return cls(**data)


@dataclass
class InteractionSequence:
    steps: List[InteractionStep] = field(default_factory=list)
    name: str = ""
    description: str = ""
    stop_on_error: bool = True
    timeout: int = 120000
    retry_failed: bool = False
    max_retries: int = 2

    def add_step(self, step: InteractionStep) -> "InteractionSequence":
        self.steps.append(step)
        return self

    def add_click(self, selector: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.CLICK, selector=selector, **kwargs))

    def add_fill(self, selector: str, text: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.FILL, selector=selector, text=text, **kwargs))

    def add_type(self, selector: str, text: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.TYPE, selector=selector, text=text, **kwargs))

    def add_hover(self, selector: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.HOVER, selector=selector, **kwargs))

    def add_wait(self, ms: int, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.WAIT, wait_ms=ms, **kwargs))

    def add_wait_for_selector(self, selector: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.WAIT_FOR_SELECTOR, wait_for_selector=selector, **kwargs))

    def add_scroll(self, delta_y: int = 500, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.SCROLL, delta_y=delta_y, **kwargs))

    def add_evaluate(self, script: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.EVALUATE, text=script, **kwargs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "stop_on_error": self.stop_on_error,
            "timeout": self.timeout,
            "retry_failed": self.retry_failed,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractionSequence":
        seq = cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            stop_on_error=data.get("stop_on_error", True),
            timeout=data.get("timeout", 120000),
            retry_failed=data.get("retry_failed", False),
            max_retries=data.get("max_retries", 2),
        )
        seq.steps = [InteractionStep.from_dict(s) for s in data.get("steps", [])]
        return seq


@dataclass
class InteractionResult:
    success: bool
    step_results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    final_url: str = ""
    final_html: str = ""
    screenshots: List[bytes] = field(default_factory=list)
    console_logs: List[Dict[str, Any]] = field(default_factory=list)
    network_requests: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "step_results": self.step_results,
            "error": self.error,
            "final_url": self.final_url,
            "final_html": self.final_html,
            "screenshots_count": len(self.screenshots),
            "console_logs_count": len(self.console_logs),
            "network_requests_count": len(self.network_requests),
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class InteractionConfig:
    default_timeout: int = 120000
    pagination_timeout: int = 120000
    default_wait_ms: int = 100
    human_like: bool = True
    min_delay_ms: int = 50
    max_delay_ms: int = 300
    scroll_behavior: str = "smooth"
    screenshot_on_error: bool = True
    capture_console: bool = True
    capture_network: bool = False
    # Enhanced human-like behavior
    enable_bezier_mouse: bool = True
    enable_reading_pauses: bool = True
    enable_random_mouse_moves: bool = True
    enable_micro_jitter: bool = True
    enable_thinking_pauses: bool = True
    enable_typo_simulation: bool = True
    reading_speed_wpm: int = 200  # words per minute
    max_thinking_pause_ms: int = 3000
    micro_jitter_radius: float = 2.0
    micro_jitter_duration: float = 0.5


class InteractionExecutor:
    def __init__(self, page: Page, config: Optional[InteractionConfig] = None):
        self.page = page
        self.config = config or InteractionConfig()
        self._console_logs: List[Dict[str, Any]] = []
        self._network_requests: List[Dict[str, Any]] = []
        self._setup_listeners()

    def _setup_listeners(self):
        if self.config.capture_console:
            self.page.on("console", self._on_console)
        if self.config.capture_network:
            self.page.on("request", self._on_request)
            self.page.on("response", self._on_response)

    def _on_console(self, msg):
        self._console_logs.append({
            "type": msg.type,
            "text": msg.text,
            "location": msg.location,
            "timestamp": asyncio.get_event_loop().time(),
        })

    def _on_request(self, request):
        self._network_requests.append({
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "timestamp": asyncio.get_event_loop().time(),
        })

    def _on_response(self, response):
        for req in self._network_requests:
            if req["url"] == response.url:
                req["status"] = response.status
                req["headers"] = dict(response.headers)
                break

    async def execute(self, sequence: InteractionSequence) -> InteractionResult:
        start_time = asyncio.get_event_loop().time()
        step_results = []
        success = True
        error = None

        for i, step in enumerate(sequence.steps):
            step_start = asyncio.get_event_loop().time()
            step_result = {
                "step_index": i,
                "action": step.action.value,
                "selector": step.selector,
                "description": step.description,
            }

            try:
                await self._execute_step(step)
                step_result["success"] = True
                step_result["elapsed_ms"] = int((asyncio.get_event_loop().time() - step_start) * 1000)

                if step.wait_ms > 0:
                    await self._human_wait(step.wait_ms)

            except Exception as e:
                step_result["success"] = False
                step_result["error"] = str(e)
                step_result["elapsed_ms"] = int((asyncio.get_event_loop().time() - step_start) * 1000)
                success = False
                error = str(e)

                if self.config.screenshot_on_error:
                    try:
                        screenshot = await self.page.screenshot(full_page=True)
                        step_result["screenshot"] = "captured"
                    except Exception:
                        pass

                if sequence.stop_on_error or step.stop_on_error:
                    break

                if sequence.retry_failed:
                    for retry in range(sequence.max_retries):
                        try:
                            await asyncio.sleep(1 * (retry + 1))
                            await self._execute_step(step)
                            step_result["success"] = True
                            step_result["error"] = None
                            success = True
                            error = None
                            break
                        except Exception as retry_e:
                            step_result["retry_error"] = str(retry_e)

            step_results.append(step_result)

        elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

        final_url = self.page.url
        final_html = ""
        screenshots = []

        try:
            final_html = await self.page.content()
        except Exception:
            pass

        return InteractionResult(
            success=success,
            step_results=step_results,
            error=error,
            final_url=final_url,
            final_html=final_html,
            screenshots=screenshots,
            console_logs=self._console_logs,
            network_requests=self._network_requests,
            elapsed_ms=elapsed_ms,
        )

    async def _execute_step(self, step: InteractionStep):
        action = step.action
        selector = step.selector
        timeout = step.timeout

        if action in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            await self._click_element(selector, action, timeout, step.options)
        elif action == ActionType.HOVER:
            await self._hover_element(selector, timeout, step.options)
        elif action == ActionType.FILL:
            await self._fill_element(selector, step.text or "", timeout, step.options)
        elif action == ActionType.TYPE:
            await self._type_element(selector, step.text or "", timeout, step.options)
        elif action == ActionType.PRESS:
            await self._press_key(step.key or "", timeout)
        elif action == ActionType.SELECT:
            await self._select_option(selector, step.text or "", timeout, step.options)
        elif action in (ActionType.CHECK, ActionType.UNCHECK):
            await self._set_checkbox(selector, action == ActionType.CHECK, timeout)
        elif action in (ActionType.FOCUS, ActionType.BLUR):
            await self._focus_blur(selector, action == ActionType.FOCUS, timeout)
        elif action == ActionType.SCROLL:
            await self._scroll(step.delta_x, step.delta_y, step.options)
        elif action == ActionType.SCROLL_INTO_VIEW:
            await self._scroll_into_view(selector, timeout)
        elif action == ActionType.WAIT:
            await asyncio.sleep(step.wait_ms / 1000)
        elif action == ActionType.WAIT_FOR_SELECTOR:
            await self.page.wait_for_selector(step.wait_for_selector, timeout=timeout)
        elif action == ActionType.WAIT_FOR_FUNCTION:
            await self.page.wait_for_function(step.wait_for_function, timeout=timeout)
        elif action == ActionType.WAIT_FOR_LOAD_STATE:
            await self.page.wait_for_load_state(step.wait_for_load_state or "networkidle", timeout=timeout)
        elif action == ActionType.WAIT_FOR_NAVIGATION:
            async with self.page.expect_navigation(timeout=timeout):
                pass
        elif action == ActionType.EVALUATE:
            await self.page.evaluate(step.text or "")
        elif action == ActionType.SCREENSHOT:
            await self.page.screenshot(**step.options)
        elif action == ActionType.DRAG_AND_DROP:
            await self._drag_and_drop(step.selector, step.options.get("target"), timeout)
        elif action == ActionType.FILE_UPLOAD:
            await self._file_upload(selector, step.options.get("files", []), timeout)
        elif action == ActionType.CLEAR:
            await self._clear_element(selector, timeout)
        elif action == ActionType.KEYBOARD:
            await self._keyboard_action(step.keys or [], step.options)
        elif action in (ActionType.MOUSE_MOVE, ActionType.MOUSE_DOWN, ActionType.MOUSE_UP):
            await self._mouse_action(action, step.x, step.y, step.options)

    async def _click_element(
        self,
        selector: str,
        action: ActionType,
        timeout: int,
        options: Dict[str, Any],
    ):
        if not selector:
            raise ValueError("Selector required for click action")

        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)

        if self.config.human_like:
            await self._human_like_click(locator)

        if action == ActionType.DOUBLE_CLICK:
            await locator.dblclick(**options)
        elif action == ActionType.RIGHT_CLICK:
            await locator.click(button="right", **options)
        else:
            await locator.click(**options)

    async def _human_like_click(self, locator: Locator):
        box = await locator.bounding_box()
        if box:
            # Add micro-jitter to click position
            x = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
            y = box["y"] + box["height"] / 2 + random.uniform(-5, 5)
            
            # Move mouse with bezier curve for natural movement
            await self._human_mouse_move(x, y)
            await asyncio.sleep(random.uniform(0.05, 0.15))
            
            # Small chance of micro-jitter before click
            if random.random() < 0.1:
                await self.page.mouse.move(
                    x + random.uniform(-1, 1),
                    y + random.uniform(-1, 1)
                )
                await asyncio.sleep(random.uniform(0.02, 0.05))

    async def _human_mouse_move(self, target_x: float, target_y: float, steps: int = None):
        """Move mouse with bezier curve for natural movement."""
        current = await self.page.evaluate("() => ({x: window.mouseX || 0, y: window.mouseY || 0})")
        start_x, start_y = current["x"], current["y"]
        
        if steps is None:
            steps = random.randint(10, 25)
        
        # Generate control points for bezier curve
        control_x = start_x + (target_x - start_x) * random.uniform(0.3, 0.7)
        control_y = start_y + (target_y - start_y) * random.uniform(0.3, 0.7)
        
        # Add some randomness to control point
        control_x += random.uniform(-50, 50)
        control_y += random.uniform(-50, 50)
        
        for i in range(steps + 1):
            t = i / steps
            # Quadratic bezier curve
            x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_x + t ** 2 * target_x
            y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_y + t ** 2 * target_y
            
            # Add micro-jitter
            x += random.uniform(-1, 1)
            y += random.uniform(-1, 1)
            
            await self.page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.005, 0.02))

    async def _human_like_type(self, text: str, delay_range: Tuple[float, float] = (50, 200)):
        """Type text with human-like timing variations."""
        for char in text:
            await self.page.keyboard.type(char)
            # Variable delay between keystrokes
            delay = random.uniform(delay_range[0], delay_range[1])
            # Occasional longer pauses (thinking pauses)
            if random.random() < 0.05:
                delay += random.uniform(200, 800)
            # Occasional backspace and retype (human error)
            if random.random() < 0.02 and len(char) == 1:
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(50, 150))
                await self.page.keyboard.type(char)
            await asyncio.sleep(delay / 1000)

    async def _reading_pause(self, text_length: int = 0):
        """Simulate reading time based on text length."""
        # Average reading speed: 200-250 words per minute
        # ~5 characters per word, so ~1000 chars per minute
        base_time = max(500, (text_length / 1000) * 60000)  # ms
        # Add variance
        pause = base_time * random.uniform(0.5, 1.5)
        # Cap at reasonable maximum
        pause = min(pause, 30000)
        await asyncio.sleep(pause / 1000)

    async def _random_mouse_move(self):
        """Perform a random mouse movement (idle behavior)."""
        viewport = await self.page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
        x = random.uniform(50, viewport["width"] - 50)
        y = random.uniform(50, viewport["height"] - 50)
        await self._human_mouse_move(x, y, steps=random.randint(5, 15))

    async def _mouse_jitter(self, x: float, y: float, radius: float = 3, duration: float = 0.5):
        """Add micro-jitter to mouse position."""
        end_time = asyncio.get_event_loop().time() + duration
        while asyncio.get_event_loop().time() < end_time:
            jitter_x = x + random.uniform(-radius, radius)
            jitter_y = y + random.uniform(-radius, radius)
            await self.page.mouse.move(jitter_x, jitter_y)
            await asyncio.sleep(random.uniform(0.02, 0.05))

    async def _execute_step(self, step: InteractionStep):
        action = step.action
        selector = step.selector
        timeout = step.timeout

        if action in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            await self._click_element(selector, action, timeout, step.options)
        elif action == ActionType.HOVER:
            await self._hover_element(selector, timeout, step.options)
        elif action == ActionType.FILL:
            await self._fill_element(selector, step.text or "", timeout, step.options)
        elif action == ActionType.TYPE:
            await self._type_element(selector, step.text or "", timeout, step.options)
        elif action == ActionType.PRESS:
            await self._press_key(step.key or "", timeout)
        elif action == ActionType.SELECT:
            await self._select_option(selector, step.text or "", timeout, step.options)
        elif action in (ActionType.CHECK, ActionType.UNCHECK):
            await self._set_checkbox(selector, action == ActionType.CHECK, timeout)
        elif action in (ActionType.FOCUS, ActionType.BLUR):
            await self._focus_blur(selector, action == ActionType.FOCUS, timeout)
        elif action == ActionType.SCROLL:
            await self._scroll(step.delta_x, step.delta_y, step.options)
        elif action == ActionType.SCROLL_INTO_VIEW:
            await self._scroll_into_view(selector, timeout)
        elif action == ActionType.WAIT:
            await asyncio.sleep(step.wait_ms / 1000)
        elif action == ActionType.WAIT_FOR_SELECTOR:
            await self.page.wait_for_selector(step.wait_for_selector, timeout=timeout)
        elif action == ActionType.WAIT_FOR_FUNCTION:
            await self.page.wait_for_function(step.wait_for_function, timeout=timeout)
        elif action == ActionType.WAIT_FOR_LOAD_STATE:
            await self.page.wait_for_load_state(step.wait_for_load_state or "networkidle", timeout=timeout)
        elif action == ActionType.WAIT_FOR_NAVIGATION:
            async with self.page.expect_navigation(timeout=timeout):
                pass
        elif action == ActionType.EVALUATE:
            await self.page.evaluate(step.text or "")
        elif action == ActionType.SCREENSHOT:
            await self.page.screenshot(**step.options)
        elif action == ActionType.DRAG_AND_DROP:
            await self._drag_and_drop(selector, step.options.get("target"), timeout)
        elif action == ActionType.FILE_UPLOAD:
            await self._file_upload(selector, step.options.get("files", []), timeout)
        elif action == ActionType.CLEAR:
            await self._clear_element(selector, timeout)
        elif action == ActionType.KEYBOARD:
            await self._keyboard_action(step.keys or [], step.options)
        elif action in (ActionType.MOUSE_MOVE, ActionType.MOUSE_DOWN, ActionType.MOUSE_UP):
            await self._mouse_action(action, step.x, step.y, step.options)
        # New human-like actions
        elif action == ActionType.MOUSE_JITTER:
            await self._mouse_jitter(step.x or 0, step.y or 0, 
                                    step.options.get("radius", 3),
                                    step.options.get("duration", 0.5))
        elif action == ActionType.READING_PAUSE:
            await self._reading_pause(step.options.get("text_length", 0))
        elif action == ActionType.RANDOM_MOUSE_MOVE:
            await self._random_mouse_move()
        # Pagination-specific actions
        elif action == ActionType.PAGINATION_CLICK:
            await self._pagination_click(selector, timeout or self.config.pagination_timeout, step.options)


class InfiniteScrollHandler:
    def __init__(self, executor: InteractionExecutor, config: InteractionConfig):
        self.executor = executor
        self.config = config

    async def scroll_until_end(
        self,
        max_iterations: int = 10,
        wait_ms: int = 1000,
        scroll_selector: Optional[str] = None,
        stop_condition: Optional[Callable[[str], Awaitable[bool]]] = None,
    ) -> InteractionResult:
        sequence = InteractionSequence(name="infinite_scroll", stop_on_error=False)

        for i in range(max_iterations):
            if scroll_selector:
                sequence.add_step(InteractionStep(
                    action=ActionType.SCROLL_INTO_VIEW,
                    selector=scroll_selector,
                    wait_ms=wait_ms,
                ))
            else:
                sequence.add_step(InteractionStep(
                    action=ActionType.SCROLL,
                    delta_y=1000,
                    wait_ms=wait_ms,
                ))

            if stop_condition:
                sequence.add_step(InteractionStep(
                    action=ActionType.EVALUATE,
                    text=f"window.__scroll_check = {stop_condition.__name__}()",
                ))

        return await self.executor.execute(sequence)


# Universal pagination selectors for common patterns across sites
UNIVERSAL_PAGINATION_SELECTORS = [
    # Next page buttons/links (visible UI elements only)
    'a.next-page',
    'a.next_page',
    'a.pagination-next',
    'a.page-next',
    'a.pager-next',
    'button.next-page',
    'button.pagination-next',
    'button:has-text("Next")',
    'a:has-text("Next")',
    'button:has-text("Next Page")',
    'a:has-text("Next Page")',
    # Load More buttons
    'button:has-text("Load More")',
    'a:has-text("Load More")',
    'button:has-text("Load more")',
    'a:has-text("Load more")',
    'button.load-more',
    'a.load-more',
    'button.load_more',
    'a.load_more',
    'button.show-more',
    'a.show-more',
    'button.view-more',
    'a.view-more',
    # Infinite scroll triggers
    '[data-infinite-scroll]',
    '[data-load-more]',
    '[data-auto-load]',
    # Numbered pagination
    '.pagination a:last-child',
    '.pager a:last-child',
    '.pagination .current + a',
    '.pager .current + a',
    '.pages a:last-child',
    # Generic next/load more
    'button:has-text("Show More")',
    'a:has-text("Show More")',
    'button:has-text("Show more")',
    'a:has-text("Show more")',
    'button:has-text("View More")',
    'a:has-text("View More")',
    'button:has-text("View more")',
    'a:has-text("View more")',
    # W3C / ARIA / semantic standards (site-agnostic, work across any site)
    '[aria-label*="Next" i]',         # ARIA: any element with Next in label (case-insensitive)
    '[aria-label*="next" i]',
    '[aria-label*="Previous" i]',     # ARIA: previous page (some sites only have prev)
    '[aria-label*="previous" i]',
    '[role="navigation"][aria-label*="pagination" i] a',  # nav role + pagination label
    'nav[aria-label*="pagination" i] a',                   # nav element with pagination
    'nav[aria-label*="pager" i] a',
    # NOTE: [rel="next"] and link[rel="next"] removed — they match hidden <link> tags, not clickable elements
    'button[type="button"][class*="next" i]',  # class-substring with case-insensitive
    'a[class*="next" i]',
    'a[href*="page="][href*="next" i]',  # URL-param: page=next pattern
    'a[href*="p="][href*="next" i]',
    'a[href*="/page/"][href$="2"]',   # URL-path: /page/N where N>1
    'a[href$="?page=2"]',
    'a[href$="&page=2"]',
    # Standard W3C / common framework patterns
    '.page-numbers .next',
    '.pagination .next',
    '.pager .next',
    '.pages .next',
    '.woocommerce-pagination .next',
    '.ais-Pagination-item--next',
    '.pagination__item--next',
    # Common BEM / OOCSS variants
    '[class*="Pagination"] [class*="next" i]',
    '[class*="paginator"] [class*="next" i]',
    '[class*="page-nav"] [class*="next" i]',
    '[class*="pageNav"] [class*="next" i]',
]


class PaginationHandler:
    """Universal pagination handler with retry logic and multiple selector fallbacks."""
    
    def __init__(self, executor: InteractionExecutor, config: InteractionConfig):
        self.executor = executor
        self.config = config
        self.logger = logging.getLogger("pagination_handler")
    
    async def click_next_page(
        self,
        custom_selectors: Optional[List[str]] = None,
        max_retries: int = 3,
        base_timeout: int = 60000,
    ) -> InteractionResult:
        """
        Click next page with universal selectors and retry logic.
        
        Args:
            custom_selectors: Optional custom selectors to try first
            max_retries: Maximum number of retry attempts
            base_timeout: Base timeout in milliseconds (default 60s)
        """
        # Build selector list: custom first, then universal fallbacks
        selectors = []
        if custom_selectors:
            selectors.extend(custom_selectors)
        selectors.extend(UNIVERSAL_PAGINATION_SELECTORS)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_selectors = []
        for sel in selectors:
            if sel not in seen:
                seen.add(sel)
                unique_selectors.append(sel)
        
        last_error = None
        
        for attempt in range(max_retries):
            for selector in unique_selectors:
                try:
                    self.logger.info(f"Attempting pagination click with selector: {selector} (attempt {attempt + 1}/{max_retries})")
                    
                    # Create a pagination click step
                    step = InteractionStep(
                        action=ActionType.PAGINATION_CLICK,
                        selector=selector,
                        timeout=self.config.pagination_timeout,
                        options={"retry_attempt": attempt}
                    )
                    
                    sequence = InteractionSequence(
                        name=f"pagination_click_{selector}",
                        steps=[step],
                        stop_on_error=False,
                    )
                    
                    result = await self.executor.execute(sequence)
                    
                    if result.success:
                        # Wait for navigation/content to load
                        await asyncio.sleep(2)
                        return result
                    
                    last_error = result.error
                    self.logger.warning(f"Pagination click failed with selector {selector}: {result.error}")
                    
                except Exception as e:
                    last_error = str(e)
                    self.logger.warning(f"Pagination click error with selector {selector}: {e}")
            
            # Exponential backoff before retry
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 1000  # 1s, 2s, 4s...
                self.logger.info(f"Retrying pagination click in {wait_time}ms (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait_time / 1000)
        
        return InteractionResult(
            success=False,
            error=f"All pagination selectors failed after {max_retries} attempts. Last error: {last_error}",
        )
    
    async def click_load_more(
        self,
        custom_selectors: Optional[List[str]] = None,
        max_clicks: int = 10,
        wait_ms: int = 2000,
    ) -> InteractionResult:
        """Click 'Load More' button repeatedly until no more results or max clicks reached."""
        selectors = custom_selectors or [
            'button:has-text("Load More")',
            'a:has-text("Load More")',
            'button.load-more',
            'a.load-more',
            'button.show-more',
            'a.show-more',
            'button:has-text("Show More")',
            'a:has-text("Show More")',
        ]
        
        all_results = []
        
        for click_num in range(max_clicks):
            result = await self.click_next_page(custom_selectors=selectors, max_retries=2)
            
            if not result.success:
                self.logger.info(f"Load more button not found or failed after {click_num + 1} clicks")
                break
            
            all_results.append(result)
            
            # Wait for content to load
            await asyncio.sleep(wait_ms / 1000)
            
            # Check if load more button still exists
            try:
                page = self.executor.page
                button_exists = False
                for selector in selectors:
                    try:
                        element = await page.query_selector(selector)
                        if element and await element.is_visible():
                            button_exists = True
                            break
                    except Exception:
                        continue
                
                if not button_exists:
                    self.logger.info("Load more button no longer visible, stopping")
                    break
                    
            except Exception:
                break
        
        return InteractionResult(
            success=len(all_results) > 0,
            step_results=[{"clicks_performed": len(all_results)}],
        )
    
    async def scroll_until_end(
        self,
        max_iterations: int = 10,
        wait_ms: int = 1000,
        scroll_selector: Optional[str] = None,
        stop_condition: Optional[Callable[[str], Awaitable[bool]]] = None,
    ) -> InteractionResult:
        """Scroll until end of page (infinite scroll)."""
        sequence = InteractionSequence(name="infinite_scroll", stop_on_error=False)
        
        for i in range(max_iterations):
            if scroll_selector:
                sequence.add_step(InteractionStep(
                    action=ActionType.SCROLL_INTO_VIEW,
                    selector=scroll_selector,
                    wait_ms=wait_ms,
                ))
            else:
                sequence.add_step(InteractionStep(
                    action=ActionType.SCROLL,
                    delta_y=1000,
                    wait_ms=wait_ms,
                ))
            
            if stop_condition:
                sequence.add_step(InteractionStep(
                    action=ActionType.EVALUATE,
                    text=f"window.__scroll_check = {stop_condition.__name__}()",
                ))
        
        return await self.executor.execute(sequence)


async def _pagination_click(
    self,
    selector: str,
    timeout: int,
    options: Dict[str, Any],
):
    """Click pagination element with extended timeout and retry logic."""
    if not selector:
        raise ValueError("Selector required for pagination click action")
    
    locator = self.page.locator(selector).first
    
    # Wait for element to be visible with pagination timeout
    await locator.wait_for(state="visible", timeout=timeout)
    
    if self.config.human_like:
        await self._human_like_click(locator)
    
    await locator.click()
    
    # Wait for navigation or content to load
    await asyncio.sleep(1.5)


def create_interaction_executor(page: Page, config: Optional[InteractionConfig] = None) -> InteractionExecutor:
    return InteractionExecutor(page, config)