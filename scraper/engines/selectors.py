from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse


class SelectorType(Enum):
    CSS = "css"
    XPATH = "xpath"
    REGEX = "regex"
    JSONPATH = "jsonpath"


@dataclass
class SelectorConfig:
    selector: str
    selector_type: SelectorType = SelectorType.CSS
    attribute: Optional[str] = None
    regex_pattern: Optional[str] = None
    multiple: bool = False
    required: bool = False
    default: Any = None
    transform: Optional[str] = None
    clean: bool = True


@dataclass
class SelectorResult:
    success: bool
    value: Any = None
    values: List[Any] = field(default_factory=list)
    error: Optional[str] = None
    selector: str = ""
    selector_type: SelectorType = SelectorType.CSS


class SelectorEngine:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._compiled_regex: Dict[str, re.Pattern] = {}

    def extract(
        self,
        content: str,
        selectors: Dict[str, SelectorConfig],
        base_url: str = "",
    ) -> Dict[str, SelectorResult]:
        results = {}
        for field_name, selector_config in selectors.items():
            results[field_name] = self._extract_field(content, selector_config, base_url)
        return results

    def _extract_field(
        self,
        content: str,
        config: SelectorConfig,
        base_url: str,
    ) -> SelectorResult:
        try:
            if config.selector_type == SelectorType.CSS:
                return self._extract_css(content, config, base_url)
            elif config.selector_type == SelectorType.XPATH:
                return self._extract_xpath(content, config, base_url)
            elif config.selector_type == SelectorType.REGEX:
                return self._extract_regex(content, config)
            elif config.selector_type == SelectorType.JSONPATH:
                return self._extract_jsonpath(content, config)
            else:
                return SelectorResult(
                    success=False,
                    error=f"Unknown selector type: {config.selector_type}",
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
        except Exception as e:
            return SelectorResult(
                success=False,
                error=str(e),
                selector=config.selector,
                selector_type=config.selector_type,
            )

    def _extract_css(
        self,
        content: str,
        config: SelectorConfig,
        base_url: str,
    ) -> SelectorResult:
        try:
            from selectolax.parser import HTMLParser
            tree = HTMLParser(content)
        except ImportError:
            return SelectorResult(
                success=False,
                error="selectolax not installed",
                selector=config.selector,
                selector_type=config.selector_type,
            )

        if config.multiple:
            nodes = tree.css(config.selector)
            values = []
            for node in nodes:
                value = self._get_node_value(node, config, base_url)
                if value is not None:
                    values.append(value)
            return SelectorResult(
                success=len(values) > 0 or not config.required,
                value=values[0] if values else config.default,
                values=values,
                selector=config.selector,
                selector_type=config.selector_type,
            )
        else:
            node = tree.css_first(config.selector)
            if node is None:
                return SelectorResult(
                    success=not config.required,
                    value=config.default,
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
            value = self._get_node_value(node, config, base_url)
            return SelectorResult(
                success=value is not None or not config.required,
                value=value or config.default,
                selector=config.selector,
                selector_type=config.selector_type,
            )

    def _get_node_value(
        self,
        node: Any,
        config: SelectorConfig,
        base_url: str,
    ) -> Any:
        if config.attribute:
            value = node.attributes.get(config.attribute)
        else:
            value = node.text(deep=True, separator=" ").strip()

        if config.clean and value:
            value = self._clean_text(value)

        if config.transform:
            value = self._apply_transform(value, config.transform)

        return value

    def _extract_xpath(
        self,
        content: str,
        config: SelectorConfig,
        base_url: str,
    ) -> SelectorResult:
        try:
            from lxml import etree
            parser = etree.HTMLParser()
            tree = etree.fromstring(content, parser)
        except ImportError:
            return SelectorResult(
                success=False,
                error="lxml not installed",
                selector=config.selector,
                selector_type=config.selector_type,
            )

        try:
            if config.multiple:
                nodes = tree.xpath(config.selector)
                values = []
                for node in nodes:
                    value = self._get_xpath_value(node, config, base_url)
                    if value is not None:
                        values.append(value)
                return SelectorResult(
                    success=len(values) > 0 or not config.required,
                    value=values[0] if values else config.default,
                    values=values,
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
            else:
                nodes = tree.xpath(config.selector)
                if not nodes:
                    return SelectorResult(
                        success=not config.required,
                        value=config.default,
                        selector=config.selector,
                        selector_type=config.selector_type,
                    )
                value = self._get_xpath_value(nodes[0], config, base_url)
                return SelectorResult(
                    success=value is not None or not config.required,
                    value=value or config.default,
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
        except Exception as e:
            return SelectorResult(
                success=False,
                error=str(e),
                selector=config.selector,
                selector_type=config.selector_type,
            )

    def _get_xpath_value(self, node: Any, config: SelectorConfig, base_url: str) -> Any:
        if config.attribute:
            value = node.get(config.attribute)
        else:
            value = "".join(node.itertext()).strip()

        if config.clean and value:
            value = self._clean_text(value)

        if config.transform:
            value = self._apply_transform(value, config.transform)

        return value

    def _extract_regex(self, content: str, config: SelectorConfig) -> SelectorResult:
        pattern = config.regex_pattern or config.selector
        if pattern not in self._compiled_regex:
            self._compiled_regex[pattern] = re.compile(pattern, re.DOTALL | re.MULTILINE)

        regex = self._compiled_regex[pattern]

        if config.multiple:
            matches = regex.findall(content)
            values = []
            for match in matches:
                if isinstance(match, tuple):
                    values.append(match[0] if match else "")
                else:
                    values.append(match)
                if config.clean:
                    values[-1] = self._clean_text(values[-1])
            return SelectorResult(
                success=len(values) > 0 or not config.required,
                value=values[0] if values else config.default,
                values=values,
                selector=config.selector,
                selector_type=config.selector_type,
            )
        else:
            match = regex.search(content)
            if not match:
                return SelectorResult(
                    success=not config.required,
                    value=config.default,
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
            value = match.group(1) if match.groups() else match.group(0)
            if config.clean:
                value = self._clean_text(value)
            return SelectorResult(
                success=True,
                value=value,
                selector=config.selector,
                selector_type=config.selector_type,
            )

    def _extract_jsonpath(self, content: str, config: SelectorConfig) -> SelectorResult:
        try:
            import jsonpath_ng
            from jsonpath_ng.ext import parse
        except ImportError:
            return SelectorResult(
                success=False,
                error="jsonpath-ng not installed",
                selector=config.selector,
                selector_type=config.selector_type,
            )

        try:
            import json
            data = json.loads(content)
            jsonpath_expr = parse(config.selector)
            matches = [match.value for match in jsonpath_expr.find(data)]

            if config.multiple:
                values = matches
                if config.clean:
                    values = [self._clean_text(str(v)) if isinstance(v, str) else v for v in values]
                return SelectorResult(
                    success=len(values) > 0 or not config.required,
                    value=values[0] if values else config.default,
                    values=values,
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
            else:
                value = matches[0] if matches else None
                if config.clean and isinstance(value, str):
                    value = self._clean_text(value)
                return SelectorResult(
                    success=value is not None or not config.required,
                    value=value or config.default,
                    selector=config.selector,
                    selector_type=config.selector_type,
                )
        except Exception as e:
            return SelectorResult(
                success=False,
                error=str(e),
                selector=config.selector,
                selector_type=config.selector_type,
            )

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        return text

    def _apply_transform(self, value: Any, transform: str) -> Any:
        transforms = {
            "lower": lambda x: x.lower() if isinstance(x, str) else x,
            "upper": lambda x: x.upper() if isinstance(x, str) else x,
            "strip": lambda x: x.strip() if isinstance(x, str) else x,
            "int": lambda x: int(float(x)) if x else 0,
            "float": lambda x: float(x) if x else 0.0,
            "bool": lambda x: bool(x),
            "abs_url": lambda x: self._make_absolute_url(x) if isinstance(x, str) else x,
        }
        if transform in transforms:
            return transforms[transform](value)
        return value

    def _make_absolute_url(self, url: str) -> str:
        # Placeholder - would need base_url context
        return url

    def extract_with_fallback(
        self,
        content: str,
        primary: Dict[str, SelectorConfig],
        fallback: Dict[str, SelectorConfig],
        base_url: str = "",
    ) -> Dict[str, SelectorResult]:
        results = self.extract(content, primary, base_url)
        for field_name, result in results.items():
            if not result.success and field_name in fallback:
                results[field_name] = self._extract_field(content, fallback[field_name], base_url)
        return results


def create_selector_engine(config: Optional[Dict[str, Any]] = None) -> SelectorEngine:
    return SelectorEngine(config)