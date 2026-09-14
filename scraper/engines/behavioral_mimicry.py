from __future__ import annotations

import asyncio
import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
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
    # Human-like actions
    MOUSE_JITTER = "mouse_jitter"
    READING_PAUSE = "reading_pause"
    RANDOM_MOUSE_MOVE = "random_mouse_move"
    THINKING_PAUSE = "thinking_pause"
    TYPING_WITH_ERRORS = "typing_with_errors"
    SCROLL_WITH_MOMENTUM = "scroll_with_momentum"


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

    def add_reading_pause(self, text_length: int = 0, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.READING_PAUSE, options={"text_length": text_length}, **kwargs))

    def add_mouse_jitter(self, x: int, y: int, radius: float = 3.0, duration: float = 0.5, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.MOUSE_JITTER, x=x, y=y, options={"radius": radius, "duration": duration}, **kwargs))

    def add_thinking_pause(self, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.THINKING_PAUSE, **kwargs))

    def add_typing_with_errors(self, selector: str, text: str, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.TYPING_WITH_ERRORS, selector=selector, text=text, **kwargs))

    def add_scroll_with_momentum(self, delta_y: int = 1000, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.SCROLL_WITH_MOMENTUM, delta_y=delta_y, **kwargs))

    def add_random_mouse_move(self, **kwargs) -> "InteractionSequence":
        return self.add_step(InteractionStep(action=ActionType.RANDOM_MOUSE_MOVE, **kwargs))

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
    default_timeout: int = 60000
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
    typing_speed_wpm: int = 60
    typo_probability: float = 0.02
    backspace_correction_probability: float = 0.01


class HumanBehaviorEngine:
    """Engine for generating human-like browser interactions."""
    
    def __init__(self, config: Optional[InteractionConfig] = None):
        self.config = config or InteractionConfig()
        self._rng = random.Random()
        self._mouse_position = (0, 0)
    
    def generate_bezier_curve(
        self, 
        start: Tuple[float, float], 
        end: Tuple[float, float], 
        steps: Optional[int] = None,
        control_point_variance: float = 0.3
    ) -> List[Tuple[float, float]]:
        """Generate a bezier curve path for natural mouse movement."""
        if steps is None:
            steps = random.randint(10, 25)
        
        start_x, start_y = start
        end_x, end_y = end
        
        # Generate control points with some randomness
        control_x = start_x + (end_x - start_x) * random.uniform(0.3, 0.7)
        control_y = start_y + (end_y - start_y) * random.uniform(0.3, 0.7)
        
        # Add randomness to control point
        control_x += random.uniform(-100, 100) * control_point_variance
        control_y += random.uniform(-100, 100) * control_point_variance
        
        points = []
        for i in range(steps + 1):
            t = i / steps
            # Quadratic bezier curve
            x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * control_x + t ** 2 * end_x
            y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * control_y + t ** 2 * end_y
            
            # Add micro-jitter
            x += random.uniform(-1, 1)
            y += random.uniform(-1, 1)
            
            points.append((x, y))
        
        return points
    
    def human_like_type(
        self, 
        text: str, 
        delay_range: Tuple[float, float] = (50, 200),
        typo_probability: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """Generate typing actions with human-like timing and occasional typos."""
        typo_prob = typo_probability or self.config.typo_probability
        actions = []
        
        for char in text:
            actions.append({
                "type": "type_char",
                "char": char,
                "delay": random.uniform(delay_range[0], delay_range[1]) / 1000.0,
            })
            
            # Occasional longer pauses (thinking pauses)
            if random.random() < 0.05:
                actions.append({
                    "type": "pause",
                    "delay": random.uniform(200, 800) / 1000.0,
                })
            
            # Occasional backspace and retype (human error)
            if random.random() < typo_prob and len(char) == 1:
                actions.append({
                    "type": "backspace",
                    "delay": random.uniform(50, 150) / 1000.0,
                })
                actions.append({
                    "type": "type_char",
                    "char": char,
                    "delay": random.uniform(delay_range[0], delay_range[1]) / 1000.0,
                })
        
        return actions
    
    def reading_pause(self, text_length: int = 0) -> float:
        """Calculate reading time based on text length."""
        # Average reading speed: 200-250 words per minute
        # ~5 characters per word, so ~1000 chars per minute
        base_time = max(500, (text_length / 1000) * 60000)  # ms
        # Add variance
        pause = base_time * random.uniform(0.5, 1.5)
        # Cap at reasonable maximum
        pause = min(pause, self.config.max_thinking_pause_ms)
        return pause / 1000.0  # seconds
    
    def random_mouse_move(self, viewport: Dict[str, int]) -> Tuple[float, float]:
        """Generate a random mouse position within viewport."""
        x = random.uniform(50, viewport["width"] - 50)
        y = random.uniform(50, viewport["height"] - 50)
        return (x, y)
    
    def mouse_jitter(self, x: float, y: float, radius: float = 3.0, duration: float = 0.5) -> List[Tuple[float, float]]:
        """Generate micro-jitter around a position."""
        end_time = time.time() + duration
        positions = []
        while time.time() < end_time:
            jitter_x = x + random.uniform(-radius, radius)
            jitter_y = y + random.uniform(-radius, radius)
            positions.append((jitter_x, jitter_y))
        return positions
    
    def thinking_pause(self) -> float:
        """Generate a thinking pause duration."""
        return random.uniform(500, self.config.max_thinking_pause_ms) / 1000.0
    
    def scroll_with_momentum(
        self, 
        delta_y: int, 
        steps: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Generate scroll actions with momentum/easing."""
        if steps is None:
            steps = random.randint(5, 15)
        
        actions = []
        remaining = delta_y
        for i in range(steps):
            # Easing function - start fast, slow down
            progress = (i + 1) / steps
            ease = 1 - (1 - progress) ** 2  # ease-out quadratic
            step_delta = int(delta_y * (ease - (i / steps) * (2 - (i / steps))))
            if i == steps - 1:
                step_delta = remaining
            
            actions.append({
                "type": "scroll",
                "delta_y": step_delta,
                "delay": random.uniform(10, 50) / 1000.0,
            })
            remaining -= step_delta
        
        return actions


class BehavioralMimicry:
    """High-level behavioral mimicry for browser automation."""
    
    def __init__(self, page: Page, config: Optional[InteractionConfig] = None):
        self.page = page
        self.config = config or InteractionConfig()
        self.engine = HumanBehaviorEngine(config)
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
        """Execute an interaction sequence with human-like behavior."""
        start_time = time.time()
        step_results = []
        success = True
        error = None
        
        for i, step in enumerate(sequence.steps):
            step_start = time.time()
            step_result = {
                "step_index": i,
                "action": step.action.value,
                "selector": step.selector,
                "description": step.description,
            }
            
            try:
                await self._execute_step(step)
                step_result["success"] = True
                step_result["elapsed_ms"] = int((time.time() - step_start) * 1000)
                
                if step.wait_ms > 0:
                    await self._human_wait(step.wait_ms)
                
            except Exception as e:
                step_result["success"] = False
                step_result["error"] = str(e)
                step_result["elapsed_ms"] = int((time.time() - step_start) * 1000)
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
        
        elapsed_ms = int((time.time() - start_time) * 1000)
        
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
        """Execute a single interaction step with human-like behavior."""
        action = step.action
        selector = step.selector
        timeout = step.timeout
        options = step.options
        
        if action in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            await self._click_element(selector, action, timeout, options)
        elif action == ActionType.HOVER:
            await self._hover_element(selector, timeout, options)
        elif action == ActionType.FILL:
            await self._fill_element(selector, step.text or "", timeout, options)
        elif action == ActionType.TYPE:
            await self._type_element(selector, step.text or "", timeout, options)
        elif action == ActionType.PRESS:
            await self._press_key(step.key or "", timeout)
        elif action == ActionType.SELECT:
            await self._select_option(selector, step.text or "", timeout, options)
        elif action in (ActionType.CHECK, ActionType.UNCHECK):
            await self._set_checkbox(selector, action == ActionType.CHECK, timeout)
        elif action in (ActionType.FOCUS, ActionType.BLUR):
            await self._focus_blur(selector, action == ActionType.FOCUS, timeout)
        elif action == ActionType.SCROLL:
            await self._scroll(step.delta_x, step.delta_y, options)
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
            await self.page.screenshot(**options)
        elif action == ActionType.DRAG_AND_DROP:
            await self._drag_and_drop(selector, options.get("target"), timeout)
        elif action == ActionType.FILE_UPLOAD:
            await self._file_upload(selector, options.get("files", []), timeout)
        elif action == ActionType.CLEAR:
            await self._clear_element(selector, timeout)
        elif action == ActionType.KEYBOARD:
            await self._keyboard_action(options.get("keys", []), options)
        elif action in (ActionType.MOUSE_MOVE, ActionType.MOUSE_DOWN, ActionType.MOUSE_UP):
            await self._mouse_action(action, step.x, step.y, options)
        # New human-like actions
        elif action == ActionType.MOUSE_JITTER:
            await self._mouse_jitter(step.x or 0, step.y or 0, 
                                     options.get("radius", 3),
                                     options.get("duration", 0.5))
        elif action == ActionType.READING_PAUSE:
            await self._reading_pause(options.get("text_length", 0))
        elif action == ActionType.RANDOM_MOUSE_MOVE:
            await self._random_mouse_move()
        elif action == ActionType.THINKING_PAUSE:
            await self._thinking_pause()
        elif action == ActionType.TYPING_WITH_ERRORS:
            await self._type_with_errors(selector, step.text or "", timeout, options)
        elif action == ActionType.SCROLL_WITH_MOMENTUM:
            await self._scroll_with_momentum(step.delta_x, step.delta_y, options)
    
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
    
    async def _human_mouse_move(self, target_x: float, target_y: float, steps: Optional[int] = None):
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
                await asyncio.sleep(random.uniform(50, 150) / 1000)
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
        end_time = time.time() + duration
        while time.time() < end_time:
            jitter_x = x + random.uniform(-radius, radius)
            jitter_y = y + random.uniform(-radius, radius)
            await self.page.mouse.move(jitter_x, jitter_y)
            await asyncio.sleep(random.uniform(0.02, 0.05))
    
    async def _execute_step(self, step: InteractionStep):
        """Execute a step with human-like behavior."""
        action = step.action
        selector = step.selector
        timeout = step.timeout
        options = step.options
        
        if action in (ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
            await self._click_element(selector, action, timeout, options)
        elif action == ActionType.HOVER:
            await self._hover_element(selector, timeout, options)
        elif action == ActionType.FILL:
            await self._fill_element(selector, step.text or "", timeout, options)
        elif action == ActionType.TYPE:
            await self._type_element(selector, step.text or "", timeout, options)
        elif action == ActionType.PRESS:
            await self._press_key(step.key or "", timeout)
        elif action == ActionType.SELECT:
            await self._select_option(selector, step.text or "", timeout, options)
        elif action in (ActionType.CHECK, ActionType.UNCHECK):
            await self._set_checkbox(selector, action == ActionType.CHECK, timeout)
        elif action in (ActionType.FOCUS, ActionType.BLUR):
            await self._focus_blur(selector, action == ActionType.FOCUS, timeout)
        elif action == ActionType.SCROLL:
            await self._scroll(step.delta_x, step.delta_y, options)
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
            await self.page.screenshot(**options)
        elif action == ActionType.DRAG_AND_DROP:
            await self._drag_and_drop(selector, options.get("target"), timeout)
        elif action == ActionType.FILE_UPLOAD:
            await self._file_upload(selector, options.get("files", []), timeout)
        elif action == ActionType.CLEAR:
            await self._clear_element(selector, timeout)
        elif action == ActionType.KEYBOARD:
            await self._keyboard_action(options.get("keys", []), options)
        elif action in (ActionType.MOUSE_MOVE, ActionType.MOUSE_DOWN, ActionType.MOUSE_UP):
            await self._mouse_action(action, step.x, step.y, options)
        # New human-like actions
        elif action == ActionType.MOUSE_JITTER:
            await self._mouse_jitter(step.x or 0, step.y or 0, 
                                     options.get("radius", 3),
                                     options.get("duration", 0.5))
        elif action == ActionType.READING_PAUSE:
            await self._reading_pause(options.get("text_length", 0))
        elif action == ActionType.RANDOM_MOUSE_MOVE:
            await self._random_mouse_move()
        elif action == ActionType.THINKING_PAUSE:
            await self._thinking_pause()
        elif action == ActionType.TYPING_WITH_ERRORS:
            await self._type_with_errors(selector, step.text or "", timeout, options)
        elif action == ActionType.SCROLL_WITH_MOMENTUM:
            await self._scroll_with_momentum(step.delta_x, step.delta_y, options)
    
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
    
    async def _human_mouse_move(self, target_x: float, target_y: float, steps: Optional[int] = None):
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
                await asyncio.sleep(random.uniform(50, 150) / 1000)
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
        end_time = time.time() + duration
        while time.time() < end_time:
            jitter_x = x + random.uniform(-radius, radius)
            jitter_y = y + random.uniform(-radius, radius)
            await self.page.mouse.move(jitter_x, jitter_y)
            await asyncio.sleep(random.uniform(0.02, 0.05))
    
    async def _thinking_pause(self):
        """Simulate a thinking pause."""
        pause = random.uniform(500, 3000) / 1000.0
        await asyncio.sleep(pause)
    
    async def _type_with_errors(self, selector: str, text: str, timeout: int, options: Dict[str, Any]):
        """Type text with human-like errors and corrections."""
        if not selector:
            raise ValueError("Selector required for type action")
        
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        
        await locator.click()
        await asyncio.sleep(random.uniform(0.05, 0.15))
        
        for char in text:
            await self.page.keyboard.type(char)
            delay = random.uniform(50, 200)
            # Occasional longer pauses (thinking pauses)
            if random.random() < 0.05:
                delay += random.uniform(200, 800)
            # Occasional backspace and retype (human error)
            if random.random() < 0.02 and len(char) == 1:
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(50, 150) / 1000)
                await self.page.keyboard.type(char)
            await asyncio.sleep(delay / 1000)
    
    async def _scroll_with_momentum(self, delta_x: int, delta_y: int, options: Dict[str, Any]):
        """Scroll with momentum/easing."""
        steps = options.get("steps", random.randint(5, 15))
        remaining_y = delta_y
        remaining_x = delta_x
        
        for i in range(steps):
            # Easing function - start fast, slow down
            progress = (i + 1) / steps
            ease = 1 - (1 - progress) ** 2  # ease-out quadratic
            
            step_y = int(delta_y * (ease - (i / steps) * (2 - (i / steps))))
            step_x = int(delta_x * (ease - (i / steps) * (2 - (i / steps))))
            
            if i == steps - 1:
                step_x = remaining_x
                step_y = remaining_y
            
            await self.page.mouse.wheel(step_x, step_y)
            await asyncio.sleep(random.uniform(10, 50) / 1000)
            remaining_y -= step_y
            remaining_x -= step_x
    
    async def _human_wait(self, ms: int):
        """Wait with small random variation."""
        variation = random.uniform(0.8, 1.2)
        await asyncio.sleep(ms * variation / 1000)
    
    async def _hover_element(self, selector: str, timeout: int, options: Dict[str, Any]):
        if not selector:
            raise ValueError("Selector required for hover action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        if self.config.human_like:
            await self._human_like_hover(locator)
        await locator.hover()
    
    async def _human_like_hover(self, locator):
        box = await locator.bounding_box()
        if box:
            x = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
            y = box["y"] + box["height"] / 2 + random.uniform(-5, 5)
            await self._human_mouse_move(x, y)
            await asyncio.sleep(random.uniform(0.05, 0.15))
    
    async def _fill_element(self, selector: str, text: str, timeout: int, options: Dict[str, Any]):
        if not selector:
            raise ValueError("Selector required for fill action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.fill(text, **options)
    
    async def _type_element(self, selector: str, text: str, timeout: int, options: Dict[str, Any]):
        if not selector:
            raise ValueError("Selector required for type action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        
        if self.config.human_like:
            await self._human_like_type(text)
        else:
            await locator.type(text, **options)
    
    async def _press_key(self, key: str, timeout: int):
        await self.page.keyboard.press(key)
    
    async def _select_option(self, selector: str, text: str, timeout: int, options: Dict[str, Any]):
        if not selector:
            raise ValueError("Selector required for select action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.select_option(label=text, **options)
    
    async def _set_checkbox(self, selector: str, check: bool, timeout: int):
        if not selector:
            raise ValueError("Selector required for checkbox action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        current = await locator.is_checked()
        if current != check:
            await locator.click()
    
    async def _focus_blur(self, selector: str, focus: bool, timeout: int):
        if not selector:
            raise ValueError("Selector required for focus/blur action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        if focus:
            await locator.focus()
        else:
            await locator.blur()
    
    async def _scroll(self, delta_x: int, delta_y: int, options: Dict[str, Any]):
        await self.page.mouse.wheel(delta_x, delta_y)
    
    async def _scroll_into_view(self, selector: str, timeout: int):
        if not selector:
            raise ValueError("Selector required for scroll into view")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.scroll_into_view_if_needed()
    
    async def _drag_and_drop(self, selector: str, target: Optional[str], timeout: int):
        if not selector or not target:
            raise ValueError("Selector and target required for drag and drop")
        source = self.page.locator(selector).first
        target_loc = self.page.locator(target).first
        await source.wait_for(state="visible", timeout=timeout)
        await target_loc.wait_for(state="visible", timeout=timeout)
        await source.drag_to(target_loc)
    
    async def _file_upload(self, selector: str, files: List[str], timeout: int):
        if not selector:
            raise ValueError("Selector required for file upload")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.set_input_files(files)
    
    async def _clear_element(self, selector: str, timeout: int):
        if not selector:
            raise ValueError("Selector required for clear action")
        locator = self.page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        await locator.clear()
    
    async def _keyboard_action(self, keys: List[str], options: Dict[str, Any]):
        for key in keys:
            await self.page.keyboard.press(key)
            await asyncio.sleep(random.uniform(0.05, 0.15))
    
    async def _mouse_action(self, action: ActionType, x: Optional[int], y: Optional[int], options: Dict[str, Any]):
        if action == ActionType.MOUSE_MOVE:
            if x is not None and y is not None:
                await self.page.mouse.move(x, y)
        elif action == ActionType.MOUSE_DOWN:
            if x is not None and y is not None:
                await self.page.mouse.down(x, y)
        elif action == ActionType.MOUSE_UP:
            if x is not None and y is not None:
                await self.page.mouse.up(x, y)


def create_interaction_executor(page: Page, config: Optional[InteractionConfig] = None) -> BehavioralMimicry:
    """Factory function to create behavioral mimicry executor."""
    return BehavioralMimicry(page, config)