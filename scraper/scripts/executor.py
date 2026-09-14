"""Script executor module for running generated scripts."""

import asyncio
import builtins
import importlib.util
import json
import logging
import os
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Awaitable

from ..config.schemas import UniversalRequest, UniversalResult, OutputFormat, EngineType
from ..universal_runner import UniversalRunner, UniversalConfig
from ..config import UniversalConfig
from ..config.schemas import UniversalRequest as UniversalRequestSchema

logger = logging.getLogger(__name__)


@dataclass
class ExecutionConfig:
    """Configuration for script execution."""
    timeout: int = 300  # 5 minutes default
    max_retries: int = 2
    retry_delay: float = 5.0
    capture_output: bool = True
    capture_errors: bool = True
    working_dir: Optional[str] = None
    env_vars: Dict[str, str] = field(default_factory=dict)
    max_memory_mb: int = 1024
    max_cpu_percent: float = 80.0


@dataclass
class ExecutionResult:
    """Result of script execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    execution_time: float = 0.0
    memory_used_mb: float = 0.0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    artifacts: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class GeneratedScriptExecutor:
    """Executes generated scraper scripts with monitoring and error handling."""
    
    def __init__(self, config: Optional[ExecutionConfig] = None):
        self.config = config or ExecutionConfig()
        self.logger = logging.getLogger("script_executor")
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._process = None
    
    async def execute_script(
        self,
        script_path: str,
        request_data: Optional[Dict[str, Any]] = None,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute a generated script file."""
        config = config or self.config
        start_time = time.time()
        
        script_path = Path(script_path)
        if not script_path.exists():
            return ExecutionResult(
                success=False,
                error=f"Script not found: {script_path}",
                exit_code=-1,
            )
        
        # Validate script
        validation_result = await self._validate_script(script_path)
        if not validation_result[0]:
            return ExecutionResult(
                success=False,
                error=f"Script validation failed: {validation_result[1]}",
                exit_code=-1,
            )
        
        start_time = time.time()
        stdout_buffer = []
        stderr_buffer = []
        
        try:
            # Prepare execution environment
            env = os.environ.copy()
            env.update(self.config.env_vars)
            if request_data:
                env["SCRAPER_REQUEST_DATA"] = json.dumps(request_data)
            
            # Prepare command
            cmd = [sys.executable, str(script_path)]
            
            # Set working directory
            cwd = self.config.working_dir or script_path.parent
            
            # Start process
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024,  # 1MB buffer
            )
            
            # Monitor execution
            try:
                stdout, stderr = await asyncio.wait_for(
                    self._process.communicate(),
                    timeout=self.config.timeout,
                )
                
                stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
                stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
                
                stdout_buffer.append(stdout_text)
                stderr_buffer.append(stderr_text)
                
                exit_code = self._process.returncode
                execution_time = time.time() - start_time
                
                if exit_code == 0:
                    # Try to parse result from stdout
                    result_data = None
                    try:
                        # Try to parse JSON output
                        output_lines = stdout_text.strip().split('\n')
                        for line in reversed(output_lines):
                            if line.strip().startswith('{'):
                                result_data = json.loads(line)
                                break
                    except Exception:
                        pass
                    
                    return ExecutionResult(
                        success=True,
                        result=result_data,
                        execution_time=execution_time,
                        stdout=stdout_text,
                        stderr=stderr_text,
                        exit_code=exit_code,
                        completed_at=datetime.utcnow().isoformat(),
                    )
                else:
                    return ExecutionResult(
                        success=False,
                        error=f"Process exited with code {exit_code}",
                        stderr=stderr_text,
                        stdout=stdout_text,
                        exit_code=exit_code,
                        execution_time=time.time() - start_time,
                        completed_at=datetime.utcnow().isoformat(),
                    )
                    
            except asyncio.TimeoutError:
                # Kill process on timeout
                if self._process:
                    self._process.kill()
                    await self._process.wait()
                
                return ExecutionResult(
                    success=False,
                    error=f"Execution timed out after {self.config.timeout} seconds",
                    execution_time=time.time() - start_time,
                    stderr="Execution timeout",
                    exit_code=-1,
                )
            
            except Exception as e:
                return ExecutionResult(
                    success=False,
                    error=f"Execution error: {str(e)}",
                    traceback=traceback.format_exc(),
                    execution_time=time.time() - start_time,
                    completed_at=datetime.utcnow().isoformat(),
                )
        
        finally:
            self._process = None

    def _validate_script(self, script_path: Path) -> tuple[bool, str]:
        """Validate a script before execution."""
        try:
            # Check file exists and is readable
            if not script_path.exists():
                return False, f"Script not found: {script_path}"
            
            if not os.access(script_path, os.R_OK):
                return False, f"Script not readable: {script_path}"
            
            # Check Python syntax
            with open(script_path, 'r') as f:
                source = script_path.read_text()
            
            try:
                compile(source, str(script_path), 'exec')
            except SyntaxError as e:
                return False, f"Syntax error in script: {e}"
            
            # Check for required imports
            required_imports = ['asyncio', 'sys', 'json']
            for imp in required_imports:
                if f"import {imp}" not in source and f"from {imp}" not in source:
                    # Warning but not fatal
                    pass
            
            return True, "Script validation passed"
            
        except Exception as e:
            return False, f"Validation error: {e}"

    async def execute_with_monitoring(
        self,
        script_path: str,
        request_data: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute script with progress monitoring."""
        # This would integrate with a progress tracking system
        # For now, just execute normally
        return await self.execute_script(script_path, request_data, config)
    
    async def execute_with_retry(
        self,
        script_path: str,
        request_data: Optional[Dict[str, Any]] = None,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """Execute script with retry logic."""
        config = config or self.config
        last_error = None
        
        for attempt in range(config.max_retries + 1):
            result = await self.execute_script(script_path, request_data, config)
            
            if result.success:
                return result
            
            last_error = result.error
            
            if attempt < config.max_retries:
                delay = self.config.retry_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(f"Attempt {attempt + 1} failed: {last_error}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
        
        # All retries exhausted
        return ExecutionResult(
            success=False,
            error=f"All {config.max_retries + 1} attempts failed. Last error: {last_error}",
            execution_time=0,
            exit_code=-1,
        )
    
    async def terminate(self, task_id: str) -> bool:
        """Terminate a running task."""
        if task_id in self._running_tasks:
            task = self._running_tasks[task_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._running_tasks[task_id]
            return True
        return False
    
    def get_running_tasks(self) -> Dict[str, Dict[str, Any]]:
        """Get information about running tasks."""
        return {
            task_id: {
                "started_at": task.get("started_at"),
                "status": "running" if not task.done() else "completed",
            }
            for task_id, task in self._running_tasks.items()
        }

    async def run_in_process(self, script: "GeneratedScript", request: "UniversalRequest") -> "UniversalResult":
        """
        Execute a GeneratedScript in-process by writing it to a temp file and running with runpy.
        Used by the orchestrator when ExecutionMode.IN_PROCESS is selected.
        """
        import asyncio as _asyncio
        import runpy
        from pathlib import Path
        import tempfile

        # Write the generated script to a temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="generated_scraper_",
            dir=self.config.working_dir or tempfile.gettempdir(),
            delete=False,
            encoding="utf-8",
        ) as f:
            # Combine config + main into one executable script
            combined_code = f'''"""Generated scraper script - combined for execution"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

{script.config_code}

{script.main_code}
'''
            f.write(combined_code)
            script_path = f.name

        try:
            # Prepare execution environment
            env = os.environ.copy()
            env.update(self.config.env_vars)
            env["SCRAPER_REQUEST_DATA"] = json.dumps({
                "url": request.url,
                "goal": request.goal,
                "max_pages": request.max_pages,
                "depth": request.depth,
                "extract_schema": request.extract_schema,
            })

            # Use runpy to execute the script properly with __file__ and __name__ set correctly
            def _run_script():
                return runpy.run_path(script_path, run_name="__main__", init_globals={"__file__": script_path})

            # Run in executor to avoid blocking the event loop
            result_container = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: runpy.run_path(script_path, run_name="__main__", init_globals={"__file__": script_path})
            )

            # The script should have printed JSON output to stdout
            # For now, return a basic result
            from ..config.schemas import UniversalResult
            return UniversalResult(
                success=True,
                url=request.url,
                data={"message": "Script executed successfully"},
                engine_used="generated_in_process",
                quality_score=0.5,
            )

        except Exception as e:
            import traceback
            self.logger.error(f"In-process execution failed: {e}\n{traceback.format_exc()}")
            raise
        finally:
            # Cleanup temp file
            try:
                os.unlink(script_path)
            except OSError:
                pass

    async def run_subprocess(self, script: "GeneratedScript", request: "UniversalRequest") -> "UniversalResult":
        """
        Execute a GeneratedScript as a subprocess by writing it to a temp file.
        Used by the orchestrator when ExecutionMode.SUBPROCESS is selected.
        """
        import asyncio as _asyncio

        # Write script to a temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="generated_scraper_",
            dir=self.config.working_dir or tempfile.gettempdir(),
            delete=False,
        ) as f:
            # Combine config + main into one executable script
            combined_code = f'''"""Generated scraper script - combined for execution"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

{script.config_code}

{script.main_code}
'''
            f.write(combined_code)
            script_path = f.name

        try:
            # Prepare execution environment
            env = os.environ.copy()
            env.update(self.config.env_vars)
            env["SCRAPER_REQUEST_DATA"] = json.dumps({
                "url": request.url,
                "goal": request.goal,
                "max_pages": request.max_pages,
                "depth": request.depth,
            })

            # Execute as subprocess
            proc = await _asyncio.create_subprocess_exec(
                sys.executable,
                script_path,
                env=env,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await _asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.config.timeout,
                )
            except _asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"Script execution timed out after {self.config.timeout}s")

            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            if proc.returncode != 0:
                raise RuntimeError(f"Script failed (exit {proc.returncode}): {stderr_text[:500]}")

            # Parse the script's JSON output from stdout
            result_data = None
            for line in reversed(stdout_text.strip().split("\n")):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        result_data = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue

            return self._parse_script_output(result_data, request, "subprocess")

        finally:
            # Cleanup temp file
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def _parse_script_output(
        self,
        result_data: Optional[Dict[str, Any]],
        request: "UniversalRequest",
        engine: str,
    ) -> "UniversalResult":
        """Convert script execution output to UniversalResult."""
        from ..config.schemas import UniversalResult

        if result_data is None:
            return UniversalResult(
                success=False,
                url=request.url,
                error="No valid JSON output from generated script",
                engine_used=engine,
            )

        # The generated script prints status lines; try to extract useful data
        success = "SUCCESS" in str(result_data) or result_data.get("success", False)
        data = result_data.get("data", result_data)

        return UniversalResult(
            success=success,
            url=request.url,
            data=data,
            engine_used=engine,
            quality_score=0.8 if success else 0.0,
            error=result_data.get("error") if not success else None,
        )

    async def _wrap_script_result(
        self,
        script: "GeneratedScript",
        request: "UniversalRequest",
        engine: str,
    ) -> "UniversalResult":
        """Wrap in-process script execution into a UniversalResult."""
        from ..config.schemas import UniversalResult

        # Since the generated script calls runner.scrape() internally,
        # the result is the exit code printed to stdout.
        # Return a basic result indicating execution completed.
        return UniversalResult(
            success=True,
            url=request.url,
            data={},
            engine_used=f"{engine}_generated",
            quality_score=0.5,
        )


async def run_generated_script(
    script_path: str,
    request_data: Optional[Dict[str, Any]] = None,
    config: Optional[ExecutionConfig] = None,
) -> ExecutionResult:
    """Convenience function to run a generated script."""
    executor = GeneratedScriptExecutor(config)
    return await executor.execute_script(script_path, request_data, config)