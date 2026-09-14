from __future__ import annotations

import re
import math
import unicodedata
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union, Set, Pattern
from pathlib import Path
from urllib.parse import urlparse

from .config.schemas import (
    UniversalConfig,
    UniversalResult,
    DataValidation,
    ValidationMode,
    OutputFormat,
)
from .utils.observability import get_logger


# Currency codes (ISO 4217)
CURRENCY_SYMBOLS = {
    '$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'JPY', '₹': 'INR',
    '₽': 'RUB', '₩': 'KRW', '₪': 'ILS', '₺': 'TRY', '₫': 'VND',
    '₦': 'NGN', '₡': 'CRC', '₱': 'PHP', '₴': 'UAH', '₵': 'GHS',
}

CURRENCY_CODES = set(CURRENCY_SYMBOLS.values()) | {
    'USD', 'EUR', 'GBP', 'JPY', 'INR', 'CAD', 'AUD', 'CHF', 'CNY',
    'HKD', 'SGD', 'SEK', 'NOK', 'DKK', 'PLN', 'CZK', 'HUF', 'RON',
    'BGN', 'HRK', 'RUB', 'BRL', 'MXN', 'ZAR', 'TRY', 'ILS', 'AED',
    'SAR', 'QAR', 'KWD', 'BHD', 'OMR', 'JOD', 'LBP', 'EGP', 'MAD',
    'TND', 'DZD', 'KES', 'UGX', 'TZS', 'NGN', 'GHS', 'XOF', 'XAF',
    'ZAR', 'BWP', 'NAD', 'MUR', 'SCR', 'SZL', 'LSL', 'MZN', 'AOA',
    'KZT', 'UZS', 'KGS', 'TJS', 'AFN', 'PKR', 'BDT', 'LKR', 'NPR',
    'BTN', 'MVR', 'MMK', 'LAK', 'KHR', 'VND', 'IDR', 'MYR', 'SGD',
    'THB', 'PHP', 'TWD', 'KRW', 'HKD', 'MOP', 'CNY', 'JPY',
}


class DataNormalizer:
    """Comprehensive data normalizer for all field types."""
    
    # Date patterns (ordered by specificity)
    DATE_PATTERNS: List = [
        # ISO 8601 with timezone
        (re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$'), 'iso_datetime'),
        # ISO 8601 date only
        (re.compile(r'^\d{4}-\d{2}-\d{2}$'), 'iso_date'),
        # Unix timestamp (seconds or ms)
        (re.compile(r'^\d{10}$'), 'unix_seconds'),
        (re.compile(r'^\d{13}$'), 'unix_millis'),
        # Common formats
        (re.compile(r'^\d{2}/\d{2}/\d{4}$'), 'mm/dd/yyyy'),
        (re.compile(r'^\d{2}-\d{2}-\d{4}$'), 'dd-mm-yyyy'),
        (re.compile(r'^\d{4}/\d{2}/\d{2}$'), 'yyyy/mm/dd'),
        (re.compile(r'^\d{2}\.\d{2}\.\d{4}$'), 'dd.mm.yyyy'),
        (re.compile(r'^\d{2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}$', re.I), 'dd Mon yyyy'),
        (re.compile(r'^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}$', re.I), 'Mon dd, yyyy'),
        (re.compile(r'^\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}$', re.I), 'dd Mon yyyy'),
    ]
    
    # Relative time patterns
    RELATIVE_TIME_PATTERNS = [
        (re.compile(r'(\d+)\s*(?:sec|second)s?\s*ago', re.I), lambda m: timedelta(seconds=int(m.group(1)))),
        (re.compile(r'(\d+)\s*(?:min|minute)s?\s*ago', re.I), lambda m: timedelta(minutes=int(m.group(1)))),
        (re.compile(r'(\d+)\s*(?:hr|hour)s?\s*ago', re.I), lambda m: timedelta(hours=int(m.group(1)))),
        (re.compile(r'(\d+)\s*(?:day)s?\s*ago', re.I), lambda m: timedelta(days=int(m.group(1)))),
        (re.compile(r'(\d+)\s*(?:week)s?\s*ago', re.I), lambda m: timedelta(weeks=int(m.group(1)))),
        (re.compile(r'(\d+)\s*(?:month)s?\s*ago', re.I), lambda m: timedelta(days=int(m.group(1))*30)),
        (re.compile(r'(\d+)\s*(?:year)s?\s*ago', re.I), lambda m: timedelta(days=int(m.group(1))*365)),
        (re.compile(r'just now', re.I), lambda m: timedelta(0)),
        (re.compile(r'a moment ago', re.I), lambda m: timedelta(seconds=30)),
    ]
    
    # Boolean patterns
    TRUE_PATTERNS = {'true', 'yes', 'y', '1', 'on', 'enabled', 'active', 't', 'y', 'on', 'enable', 'allow'}
    FALSE_PATTERNS = {'false', 'no', 'n', '0', 'off', 'disabled', 'inactive', 'f', 'n', 'off', 'disable', 'deny', 'block'}
    
    def __init__(self):
        self._compiled_patterns = self._compile_patterns()
    
    def _compile_patterns(self) -> Dict:
        patterns = {}
        for pattern, fmt in self.DATE_PATTERNS:
            patterns[fmt] = pattern
        return patterns
    
    def normalize(self, field: str, value: Any, rule: Optional[str] = None) -> Any:
        """Normalize a value based on field name, rule, or inferred type."""
        if value is None:
            return None
        
        field_lower = field.lower()
        
        # Explicit rule takes precedence
        if rule:
            return self._apply_rule(value, rule)
        
        # Infer from field name
        field_lower = field.lower()
        
        if any(kw in field_lower for kw in ['date', 'time', 'created', 'updated', 'published', 'modified', 'timestamp']):
            return self.normalize_datetime(value)
        
        if any(kw in field_lower for kw in ['price', 'cost', 'amount', 'fee', 'rate', 'salary', 'wage', 'budget', 'revenue', 'income', 'expense', 'fare']):
            return self.normalize_currency(value)
        
        if any(kw in field_lower for kw in ['weight', 'mass', 'length', 'height', 'width', 'depth', 'size', 'dimension', 'distance', 'speed', 'velocity', 'volume', 'capacity', 'capacity', 'frequency', 'bandwidth', 'throughput', 'resolution', 'dpi', 'ppi']):
            return self.normalize_measurement(value)
        
        if any(kw in field_lower for kw in ['email', 'mail']):
            return self.normalize_email(value)
        
        if any(kw in field_lower for kw in ['phone', 'mobile', 'telephone', 'fax']):
            return self.normalize_phone(value)
        
        if any(kw in field_lower for kw in ['url', 'uri', 'link', 'href']):
            return self.normalize_url(value)
        
        if any(kw in field_lower for kw in ['bool', 'is_', 'has_', 'can_', 'should_', 'must_', 'enable', 'disable', 'active', 'enabled', 'visible', 'hidden']):
            return self.normalize_boolean(value)
        
        if isinstance(value, str):
            return self.normalize_text(value)
        
        if isinstance(value, list):
            return self.normalize_array(value)
        
        if isinstance(value, dict):
            return self.normalize_object(value)
        
        return value
    
    def _apply_rule(self, value: Any, rule: str) -> Any:
        """Apply explicit normalization rule."""
        rule_lower = rule.lower()
        
        if rule_lower == 'datetime':
            return self.normalize_datetime(value)
        elif rule_lower == 'date':
            return self.normalize_date(value)
        elif rule_lower == 'time':
            return self.normalize_time(value)
        elif rule_lower == 'currency':
            return self.normalize_currency(value)
        elif rule_lower == 'price':
            return self.normalize_currency(value)
        elif rule_lower == 'measurement':
            return self.normalize_measurement(value)
        elif rule_lower == 'email':
            return self.normalize_email(value)
        elif rule_lower == 'phone':
            return self.normalize_phone(value)
        elif rule_lower == 'url':
            return self.normalize_url(value)
        elif rule_lower == 'boolean':
            return self.normalize_boolean(value)
        elif rule_lower == 'text':
            return self.normalize_text(value)
        elif rule_lower == 'array':
            return self.normalize_array(value)
        elif rule_lower == 'object':
            return self.normalize_object(value)
        elif rule_lower.startswith('regex:'):
            pattern = rule[6:]
            if isinstance(value, str):
                return re.sub(pattern, '', value)
            return value
        elif rule_lower.startswith('map:'):
            # Format: map:value1->new1,value2->new2
            mapping_str = rule[4:]
            mapping = {}
            for pair in mapping_str.split(','):
                if '->' in pair:
                    k, v = pair.split('->', 1)
                    mapping[k.strip()] = v.strip()
            if isinstance(value, str) and value in mapping:
                return mapping[value]
            return value
        elif rule_lower.startswith('enum:'):
            # Format: enum:value1,value2,value3
            allowed = set(v.strip() for v in rule[5:].split(','))
            if isinstance(value, str) and value in allowed:
                return value
            return None
        elif rule_lower.startswith('range:'):
            # Format: range:min,max
            range_str = rule[6:]
            try:
                min_val, max_val = map(float, range_str.split(','))
                num = float(value) if value is not None else None
                if num is not None and min_val <= num <= max_val:
                    return num
                return None
            except (ValueError, TypeError):
                return value
        
        return value
    
    def normalize_datetime(self, value: Any) -> Optional[str]:
        """Normalize datetime to ISO 8601 UTC."""
        if value is None:
            return None
        
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        
        if isinstance(value, (int, float)):
            # Unix timestamp
            if value > 1e12:  # milliseconds
                value = value / 1000
            try:
                dt = datetime.fromtimestamp(value, tz=timezone.utc)
                return dt.isoformat()
            except (ValueError, OSError):
                pass
        
        if isinstance(value, str):
            value = value.strip()
            
            # Try ISO formats first
            try:
                dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
            
            # Try other patterns
            for pattern, fmt in self.DATE_PATTERNS:
                match = pattern.match(value)
                if match:
                    try:
                        if fmt == 'iso_datetime':
                            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        elif fmt == 'iso_date':
                            dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
                        elif fmt == 'unix_seconds':
                            dt = datetime.fromtimestamp(int(value), tz=timezone.utc)
                        elif fmt == 'unix_millis':
                            dt = datetime.fromtimestamp(int(value)/1000, tz=timezone.utc)
                        elif fmt == 'mm/dd/yyyy':
                            dt = datetime.strptime(value, '%m/%d/%Y').replace(tzinfo=timezone.utc)
                        elif fmt == 'dd-mm-yyyy':
                            dt = datetime.strptime(value, '%d-%m-%Y').replace(tzinfo=timezone.utc)
                        elif fmt == 'yyyy/mm/dd':
                            dt = datetime.strptime(value, '%Y/%m/%d').replace(tzinfo=timezone.utc)
                        elif fmt == 'dd.mm.yyyy':
                            dt = datetime.strptime(value, '%d.%m.%Y').replace(tzinfo=timezone.utc)
                        elif fmt == 'dd Mon yyyy':
                            dt = datetime.strptime(value, '%d %b %Y').replace(tzinfo=timezone.utc)
                        elif fmt == 'Mon dd, yyyy':
                            dt = datetime.strptime(value, '%b %d, %Y').replace(tzinfo=timezone.utc)
                        elif fmt == 'dd Mon yyyy':
                            dt = datetime.strptime(value, '%d %b %Y').replace(tzinfo=timezone.utc)
                        else:
                            continue
                        
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        return dt.astimezone(timezone.utc).isoformat()
                    except ValueError:
                        continue
            
            # Try relative time
            RELATIVE_TIME_PATTERNS = [
                (re.compile(r'(\d+)\s*(?:sec|second)s?\s*ago', re.I), lambda m: timedelta(seconds=int(m.group(1)))),
                (re.compile(r'(\d+)\s*(?:min|minute)s?\s*ago', re.I), lambda m: timedelta(minutes=int(m.group(1)))),
                (re.compile(r'(\d+)\s*(?:hr|hour)s?\s*ago', re.I), lambda m: timedelta(hours=int(m.group(1)))),
                (re.compile(r'(\d+)\s*(?:day)s?\s*ago', re.I), lambda m: timedelta(days=int(m.group(1)))),
                (re.compile(r'(\d+)\s*(?:week)s?\s*ago', re.I), lambda m: timedelta(weeks=int(m.group(1)))),
                (re.compile(r'(\d+)\s*(?:month)s?\s*ago', re.I), lambda m: timedelta(days=int(m.group(1))*30)),
                (re.compile(r'(\d+)\s*(?:year)s?\s*ago', re.I), lambda m: timedelta(days=int(m.group(1))*365)),
                (re.compile(r'just now', re.I), lambda m: timedelta(0)),
                (re.compile(r'a moment ago', re.I), lambda m: timedelta(seconds=30)),
            ]
            
            for pattern, td_func in RELATIVE_TIME_PATTERNS:
                match = pattern.match(value)
                if match:
                    delta = td_func(match)
                    dt = datetime.now(timezone.utc) - delta
                    return dt.isoformat()
        
        return value
    
    def normalize_date(self, value: Any) -> Optional[str]:
        """Normalize to YYYY-MM-DD format."""
        dt = self.normalize_datetime(value)
        if dt:
            return dt.split('T')[0]
        return None
    
    def normalize_time(self, value: Any) -> Optional[str]:
        """Normalize to HH:MM:SS format."""
        dt = self.normalize_datetime(value)
        if dt:
            return dt.split('T')[1].split('.')[0]
        return None
    
    def normalize_currency(self, value: Any) -> Optional[float]:
        """Extract and normalize currency value."""
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Find currency symbol
            currency = 'USD'  # default
            for symbol, code in CURRENCY_SYMBOLS.items():
                if symbol in value:
                    currency = code
                    break
            
            # Extract numeric value
            cleaned = re.sub(r'[^\d.,\-]', '', value)
            # Handle different decimal separators
            cleaned = cleaned.replace(',', '')
            try:
                return float(cleaned)
            except ValueError:
                pass
        
        return None
    
    def normalize_measurement(self, value: Any) -> Optional[Dict[str, Any]]:
        """Extract and normalize measurement with unit."""
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return {'value': float(value), 'unit': None}
        
        if isinstance(value, str):
            # Try to extract number and unit
            match = re.search(r'([\d.,]+)\s*([a-zA-Z°%µμ]+)', value)
            if match:
                try:
                    val = float(match.group(1).replace(',', ''))
                    unit = match.group(2).strip()
                    return {'value': val, 'unit': unit.lower()}
                except ValueError:
                    pass
            
            # Try to extract just number
            cleaned = re.sub(r'[^\d.\-]', '', value)
            try:
                return {'value': float(cleaned), 'unit': None}
            except ValueError:
                pass
        
        if isinstance(value, (int, float)):
            return {'value': float(value), 'unit': None}
        
        return None
    
    def normalize_email(self, value: Any) -> Optional[str]:
        """Normalize email address."""
        if value is None:
            return None
        if isinstance(value, str):
            email = value.strip().lower()
            # Basic validation
            if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
                return email
        return None
    
    def normalize_phone(self, value: Any) -> Optional[str]:
        """Normalize phone number to E.164 format."""
        if value is None:
            return None
        
        if isinstance(value, str):
            # Extract digits
            digits = re.sub(r'\D', '', value)
            
            # Handle common formats
            if len(digits) == 10:  # US without country code
                return f'+1{digits}'
            elif len(digits) == 11 and digits.startswith('1'):
                return f'+{digits}'
            elif len(digits) >= 10 and not digits.startswith('+'):
                return f'+{digits}'
            elif digits.startswith('+'):
                return value
            
            return value
        
        return value
    
    def normalize_url(self, value: Any) -> Optional[str]:
        """Normalize URL."""
        if value is None:
            return None
        
        if isinstance(value, str):
            url = value.strip()
            if not url:
                return None
            
            # Add scheme if missing
            if not url.startswith(('http://', 'https://', 'ftp://', 'mailto:')):
                if url.startswith('//'):
                    url = 'https:' + url
                else:
                    url = 'https://' + url
            
            # Basic validation
            try:
                parsed = urlparse(url)
                if parsed.scheme and parsed.netloc:
                    return url
            except Exception:
                pass
        
        return None
    
    def normalize_boolean(self, value: Any) -> Optional[bool]:
        """Normalize boolean value."""
        if value is None:
            return None
        
        if isinstance(value, bool):
            return value
        
        if isinstance(value, (int, float)):
            return bool(value)
        
        if isinstance(value, str):
            val_lower = value.strip().lower()
            if val_lower in {'true', 'yes', 'y', '1', 'on', 'enabled', 'active', 't', 'y', 'on', 'enable', 'allow'}:
                return True
            if val_lower in {'false', 'no', 'n', '0', 'off', 'disabled', 'inactive', 'f', 'n', 'off', 'disable', 'deny', 'block'}:
                return False
            
            # Try numeric
            try:
                return bool(float(value))
            except ValueError:
                pass
        
        if isinstance(value, (int, float)):
            return bool(value)
        
        return None
    
    def normalize_text(self, value: Any) -> Any:
        """Normalize text with Unicode normalization."""
        if value is None:
            return None
        
        if not isinstance(value, str):
            return str(value)
        
        # Unicode NFKC normalization
        text = unicodedata.normalize('NFKC', value)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Strip
        text = text.strip()
        
        return text if text else None
    
    def normalize_array(self, value: Any) -> List[Any]:
        """Normalize array: dedupe, normalize items."""
        if value is None:
            return []
        
        if not isinstance(value, list):
            value = [value]
        
        seen = set()
        result = []
        for item in value:
            if isinstance(item, str):
                normalized = self.normalize_text(item)
            elif isinstance(item, dict):
                normalized = self.normalize_object(item)
            else:
                normalized = item
            
            if normalized is not None:
                # Use JSON for dedupe key
                import json
                key = json.dumps(normalized, sort_keys=True) if isinstance(normalized, (dict, list)) else str(normalized)
                if key not in seen:
                    seen.add(key)
                    result.append(normalized)
        
        return result
    
    def normalize_object(self, value: Any) -> Dict[str, Any]:
        """Recursively normalize object fields."""
        if not isinstance(value, dict):
            return {}
        
        normalized = {}
        for key, val in value.items():
            normalized_key = self.normalize_text(key) or key
            normalized[normalized_key] = self.normalize(normalized_key, val)
        
        return normalized


@dataclass
class ValidationReport:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    completeness: float = 0.0
    accuracy: float = 0.0
    duplicate_rate: float = 0.0
    field_stats: Dict[str, Any] = field(default_factory=dict)
    normalization_stats: Dict[str, int] = field(default_factory=dict)
    
    # Enhanced quality metrics
    freshness: float = 0.0
    consistency: float = 0.0
    source_reliability: float = 0.0
    schema_adherence: float = 0.0
    anomaly_score: float = 0.0
    field_consistency: Dict[str, float] = field(default_factory=dict)
    type_consistency: Dict[str, float] = field(default_factory=dict)


class ResultValidator:
    """Validate and score scrape results."""

    def __init__(self, config: UniversalConfig):
        self.config = config
        self.validation_config = config.data_validation or DataValidation()
        self.normalizer = DataNormalizer()
        self.logger = get_logger("validator")

    def validate(self, result: UniversalResult, schema: Optional[Dict[str, Any]] = None) -> float:
        """Validate result and return quality score (0-1)."""
        if not result.success or not result.data:
            result.quality_score = 0.0
            return 0.0

        report = self._validate_result(result, schema)
        result.validation_report = report.__dict__

        # Compute quality score
        quality = self._compute_quality(report)
        result.quality_score = quality
        result.completeness = report.completeness
        result.accuracy = report.accuracy

        return quality

    def _validate_result(self, result: UniversalResult, schema: Optional[Dict[str, Any]] = None) -> ValidationReport:
        report = ValidationReport(valid=True)
        norm_stats = {'normalized': 0, 'failed': 0, 'by_type': {}}

        if not result.data:
            report.valid = False
            report.errors.append("No data returned")
            return report

        # Convert to list for uniform processing
        items = result.data if isinstance(result.data, list) else [result.data]

        # Use schema from parameter or fall back to config
        validation_schema = schema or self.validation_config.validation_schema

        # Normalize all items
        normalized_items = []
        for item in items:
            normalized = self.normalizer.normalize_object(item)
            normalized_items.append(normalized)
            norm_stats['normalized'] += 1

        # Check schema if provided
        if validation_schema:
            schema_errors = self._validate_schema(normalized_items, validation_schema)
            report.errors.extend(schema_errors)
            if schema_errors:
                report.valid = False

        # Check required fields
        if self.validation_config.required_fields:
            missing = self._check_required_fields(normalized_items)
            if missing:
                report.errors.extend([f"Missing required field: {f}" for f in missing])
                report.valid = False

        # Apply cleaning rules
        cleaned_items = []
        for item in normalized_items:
            cleaned = self._apply_cleaning(item)
            cleaned_items.append(cleaned)

        # Deduplication
        if self.validation_config.dedup_keys:
            dup_rate = self._check_duplicates(cleaned_items)
            report.duplicate_rate = dup_rate
            if dup_rate > 0.5:
                report.warnings.append(f"High duplicate rate: {dup_rate:.1%}")

        # Completeness: ratio of non-null fields
        report.completeness = self._compute_completeness(cleaned_items)

        # Accuracy: heuristic based on field presence
        report.accuracy = self._compute_accuracy(cleaned_items)

        # Store cleaned data
        result.cleaned_data = cleaned_items
        result.normalization_stats = norm_stats

        return report

    def _validate_schema(self, items: List[Dict[str, Any]], schema: Optional[Dict[str, Any]] = None) -> List[str]:
        try:
            import jsonschema
            errors = []
            validation_schema = schema or self.validation_config.validation_schema
            if not validation_schema:
                return []
            for i, item in enumerate(items):
                try:
                    jsonschema.validate(item, validation_schema)
                except jsonschema.ValidationError as e:
                    errors.append(f"Item {i}: {e.message}")
            return errors
        except ImportError:
            return []

    def _check_required_fields(self, items: List[Dict[str, Any]]) -> List[str]:
        missing = set()
        for item in items:
            for field in self.validation_config.required_fields:
                if field not in item or item[field] is None or item[field] == "":
                    missing.add(field)
        return list(missing)

    def _apply_cleaning(self, item: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = item.copy()
        for field, rules in self.validation_config.cleaning_rules.items():
            if field in cleaned and cleaned[field] is not None:
                value = cleaned[field]
                if isinstance(value, str):
                    for rule in rules:
                        if rule == "strip":
                            value = value.strip()
                        elif rule == "lower":
                            value = value.lower()
                        elif rule == "upper":
                            value = value.upper()
                        elif rule.startswith("regex:"):
                            pattern = rule[6:]
                            value = re.sub(pattern, "", value)
                cleaned[field] = value
        return cleaned

    def _check_duplicates(self, items: List[Dict[str, Any]]) -> float:
        if not self.validation_config.dedup_keys:
            return 0.0

        seen = set()
        duplicates = 0
        for item in items:
            key = tuple(item.get(k) for k in self.validation_config.dedup_keys)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
        return duplicates / len(items) if items else 0.0

    def _compute_completeness(self, items: List[Dict[str, Any]]) -> float:
        if not items:
            return 0.0
        total_fields = sum(len(item) for item in items)
        non_null = sum(1 for item in items for v in item.values() if v is not None and v != "")
        return non_null / total_fields if total_fields > 0 else 0.0

    def _compute_accuracy(self, items: List[Dict[str, Any]]) -> float:
        if not items:
            return 0.0
        suspicious = 0
        for item in items:
            for v in item.values():
                if isinstance(v, str) and len(v) > 5000:
                    suspicious += 1
                if isinstance(v, str) and v.isdigit() and len(v) > 20:
                    suspicious += 1
        return max(0.0, 1.0 - suspicious / (len(items) * len(items[0]) if items else 1))

    def _compute_quality(self, report: ValidationReport) -> float:
        if not report.valid:
            return 0.0

        weights = {
            "completeness": 0.35,
            "accuracy": 0.25,
            "duplicate_penalty": 0.2,
            "validity": 0.1,
            "normalization": 0.1,
        }

        quality = (
            weights["completeness"] * report.completeness +
            weights["accuracy"] * report.accuracy +
            weights["duplicate_penalty"] * (1 - min(report.duplicate_rate, 1.0)) +
            weights["validity"] * (1.0 if report.valid else 0.0) +
            weights["normalization"] * 1.0  # Assume normalization succeeded
        )

        return max(0.0, min(1.0, quality))

    def _compute_freshness(self, items: List[Dict[str, Any]]) -> float:
        """Compute freshness score based on date fields."""
        if not items:
            return 0.0
        
        date_fields = ['created', 'updated', 'published', 'modified', 'timestamp', 'date', 'created_at', 'updated_at']
        fresh_scores = []
        
        for item in items:
            for field in date_fields:
                if field in item and item[field]:
                    try:
                        date_str = str(item[field])
                        dt = self.normalizer.normalize_datetime(item[field])
                        if dt:
                            item_dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                            age_days = (datetime.now(timezone.utc) - item_dt).days
                            # Score decreases with age: 1.0 for <1 day, 0.5 for 30 days, 0.1 for 365+ days
                            if age_days <= 1:
                                freshness = 1.0
                            elif age_days <= 7:
                                freshness = 0.9
                            elif age_days <= 30:
                                freshness = 0.7
                            elif age_days <= 90:
                                freshness = 0.5
                            elif age_days <= 365:
                                freshness = 0.3
                            else:
                                freshness = 0.1
                            fresh_scores.append(freshness)
                    except (ValueError, TypeError):
                        pass
        
        return sum(fresh_scores) / len(fresh_scores) if fresh_scores else 0.5

    def _compute_consistency(self, items: List[Dict[str, Any]]) -> float:
        """Compute consistency score across items."""
        if not items or len(items) < 2:
            return 1.0
        
        # Check field presence consistency
        all_keys = set()
        for item in items:
            all_keys.update(item.keys())
        
        if not all_keys:
            return 1.0
        
        # Check how consistently each field appears
        field_presence = {}
        for key in all_keys:
            present = sum(1 for item in items if key in item and item[key] is not None)
            field_presence[key] = present / len(items)
        
        # Consistency = average field presence rate
        avg_presence = sum(field_presence.values()) / len(field_presence)
        
        # Type consistency check
        type_consistency = {}
        for key in all_keys:
            types_seen = set()
            for item in items:
                if key in item and item[key] is not None:
                    types_seen.add(type(item[key]).__name__)
            type_consistency[key] = 1.0 if len(types_seen) <= 1 else 0.5
        
        avg_type_consistency = sum(type_consistency.values()) / len(type_consistency) if type_consistency else 1.0
        
        return (avg_presence + avg_type_consistency) / 2.0

    def _compute_source_reliability(self, items: List[Dict[str, Any]]) -> float:
        """Compute source reliability based on data patterns."""
        if not items:
            return 0.5
        
        reliability_scores = []
        
        for item in items:
            score = 0.5  # Base score
            
            # Check for structured data indicators
            has_id = any(k in item for k in ['id', 'id', 'sku', 'uuid'])
            has_url = any(isinstance(v, str) and v.startswith(('http://', 'https://')) for v in item.values())
            has_structured_data = any(isinstance(v, (dict, list)) for v in item.values())
            
            if has_id:
                score += 0.2
            if has_url:
                score += 0.1
            if has_structured_data:
                score += 0.1
            
            # Check for suspiciously clean data (might be fabricated)
            text_fields = [str(v) for v in item.values() if isinstance(v, str)]
            total_text = ' '.join(text_fields)
            if len(total_text) > 100:
                # Check for repetitive patterns
                words = total_text.split()
                unique_ratio = len(set(words)) / len(words) if words else 1
                if unique_ratio < 0.3:
                    score -= 0.2  # Likely template/spam
            
            reliability_scores.append(max(0.0, min(1.0, score)))
        
        return sum(reliability_scores) / len(reliability_scores) if reliability_scores else 0.5

    def _compute_schema_adherence(self, items: List[Dict[str, Any]]) -> float:
        """Compute schema adherence score."""
        if not self.validation_config.schema or not items:
            return 1.0
        
        try:
            import jsonschema
            valid_count = 0
            for item in items:
                try:
                    jsonschema.validate(item, self.validation_config.schema)
                    valid_count += 1
                except jsonschema.ValidationError:
                    pass
            return valid_count / len(items)
        except ImportError:
            return 1.0

    def _compute_anomaly_score(self, items: List[Dict[str, Any]]) -> float:
        """Compute anomaly score (lower is better)."""
        if not items:
            return 0.0
        
        anomaly_count = 0
        total_fields = 0
        
        for item in items:
            for key, value in item.items():
                total_fields += 1
                if value is None:
                    continue
                
                # Check for suspicious patterns
                if isinstance(value, str):
                    # Extremely long values
                    if len(value) > 10000:
                        anomaly_count += 1
                    # All caps (shouting)
                    if value.isupper() and len(value) > 10:
                        anomaly_count += 1
                    # Repeated characters
                    if len(value) > 5 and len(set(value)) < 3:
                        anomaly_count += 1
                    # Suspicious patterns
                    if re.search(r'(.)\1{10,}', value):  # 10+ repeated chars
                        anomaly_count += 1
                    # SQL injection patterns
                    if re.search(r'(union|select|insert|delete|drop|exec)\s', value, re.I):
                        anomaly_count += 1
                    # Script tags
                    if '<script' in value.lower():
                        anomaly_count += 1
        
        return min(1.0, anomaly_count / max(1, total_fields))

    def _compute_field_consistency(self, items: List[Dict[str, Any]]) -> Dict[str, float]:
        """Compute per-field consistency scores."""
        if not items:
            return {}
        
        all_keys = set()
        for item in items:
            all_keys.update(item.keys())
        
        consistency = {}
        for key in all_keys:
            present_count = sum(1 for item in items if key in item and item[key] is not None)
            type_consistency = 1.0
            
            types_seen = set()
            for item in items:
                if key in item and item[key] is not None:
                    types_seen.add(type(item[key]).__name__)
            
            if len(types_seen) > 1:
                type_consistency = 0.5
            else:
                type_consistency = 1.0
            
            presence_rate = present_count / len(items)
            consistency[key] = (presence_rate + type_consistency) / 2.0
        
        return consistency

    def _compute_type_consistency(self, items: List[Dict[str, Any]]) -> Dict[str, float]:
        """Compute per-field type consistency."""
        if not items:
            return {}
        
        all_keys = set()
        for item in items:
            all_keys.update(item.keys())
        
        type_consistency = {}
        for key in all_keys:
            types_seen = set()
            for item in items:
                if key in item and item[key] is not None:
                    types_seen.add(type(item[key]).__name__)
            
            if len(types_seen) <= 1:
                type_consistency[key] = 1.0
            elif len(types_seen) == 2:
                type_consistency[key] = 0.7
            else:
                type_consistency[key] = 0.3
        
        return type_consistency

    def _compute_quality(self, report: ValidationReport) -> float:
        if not report.valid:
            return 0.0

        # Compute enhanced metrics if not already set
        if not hasattr(report, 'freshness') or report.freshness == 0.0:
            # We'll compute these in _validate_result and store in report
            pass

        weights = {
            "completeness": 0.25,
            "accuracy": 0.20,
            "duplicate_penalty": 0.15,
            "validity": 0.10,
            "normalization": 0.10,
            "freshness": 0.10,
            "consistency": 0.10,
            "source_reliability": 0.05,
            "schema_adherence": 0.05,
            "anomaly_penalty": 0.05,
        }

        # Get metrics with defaults
        freshness = getattr(report, 'freshness', 0.5)
        consistency = getattr(report, 'consistency', 0.5)
        source_reliability = getattr(report, 'source_reliability', 0.5)
        schema_adherence = getattr(report, 'schema_adherence', 1.0)
        anomaly_score = getattr(report, 'anomaly_score', 0.0)

        quality = (
            weights["completeness"] * report.completeness +
            weights["accuracy"] * report.accuracy +
            weights["duplicate_penalty"] * (1 - min(report.duplicate_rate, 1.0)) +
            weights["validity"] * (1.0 if report.valid else 0.0) +
            weights["normalization"] * 1.0 +
            weights["freshness"] * freshness +
            weights["consistency"] * consistency +
            weights["source_reliability"] * source_reliability +
            weights["schema_adherence"] * schema_adherence +
            weights["anomaly_penalty"] * (1.0 - anomaly_score)
        )

        return max(0.0, min(1.0, quality))