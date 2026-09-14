from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

from scraper.config.schemas import (
    GeneratedScript,
    ExecutionConfig,
    ExecutionMode,
    UniversalRequest,
    UniversalResult,
)
from scraper.utils.observability import get_logger


class ExecutionMode(Enum):
    IN_PROCESS = "in_process"
    SUBPROCESS = "subprocess"


@dataclass
class GeneratedScriptExecutor:
    config: ExecutionConfig
    _temp_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()) / "universal_scraper_scripts")

    def __post_init__(self):
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("executor")

    async def run_in_process(
        self, script: GeneratedScript, request: UniversalRequest
    ) -> UniversalResult:
        self.logger.info("Running script in-process", script_id=script.metadata.profile_hash)

        script_file = self._temp_dir / f"{script.metadata.profile_hash}.py"
        script_file.write_text(script.main_code)

        try:
            spec = importlib.util.spec_from_file_location("generated_script", script_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules["generated_script"] = module
            spec.loader.exec_module(module)

            if hasattr(module, "main"):
                if asyncio.iscoroutinefunction(module.main):
                    result = await module.main(request)
                else:
                    result = module.main(request)
                return self._normalize_result(result)
            else:
                raise RuntimeError("Generated script has no main() function")

        except Exception as e:
            self.logger.error("In-process execution failed", error=str(e))
            return UniversalResult(
                success=False,
                url=request.url,
                error=str(e),
                engine_used="generated_script",
            )

    async def run_subprocess(
        self, script: GeneratedScript, request: UniversalRequest
    ) -> UniversalResult:
        self.logger.info("Running script in subprocess", script_id=script.metadata.profile_hash)

        script_file = self._temp_dir / f"{script.metadata.profile_hash}.py"
        script_file.write_text(script.main_code)

        req_file = self._temp_dir / f"{script.metadata.profile_hash}_request.json"
        req_file.write_text(request.model_dump_json())

        out_file = self._temp_dir / f"{script.metadata.profile_hash}_output.json"

        cmd = [
            sys.executable, str(script_file),
            "--request", str(req_file),
            "--output", str(out_file),
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.config.timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return UniversalResult(
                    success=False,
                    url=request.url,
                    error="Execution timeout",
                    engine_used="generated_script",
                )

            if process.returncode != 0:
                return UniversalResult(
                    success=False,
                    url=request.url,
                    error=f"Script failed: {stderr.decode()}",
                    engine_used="generated_script",
                )

            if out_file.exists():
                result_data = json.loads(out_file.read_text())
                return UniversalResult(**result_data)
            else:
                return UniversalResult(
                    success=False,
                    url=request.url,
                    error="No output file produced",
                    engine_used="generated_script",
                )

        except Exception as e:
            self.logger.error("Subprocess execution failed", error=str(e))
            return UniversalResult(
                success=False,
                url=request.url,
                error=str(e),
                engine_used="generated_script",
            )

    def _normalize_result(self, result: Any) -> UniversalResult:
        if isinstance(result, UniversalResult):
            return result
        elif isinstance(result, dict):
            return UniversalResult(**result)
        elif isinstance(result, list):
            return UniversalResult(
                success=True,
                url="",
                data=result,
                engine_used="generated_script",
            )
        else:
            return UniversalResult(
                success=True,
                url="",
                data={"result": str(result)},
                engine_used="generated_script",
            )