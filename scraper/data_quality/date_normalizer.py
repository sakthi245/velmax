from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

from .models import NormalizedDate


@dataclass
class DateConfig:
    target_timezone: str = "UTC"
    default_timezone: str = "UTC"
    relative_base: Optional[datetime] = None
    locale: str = "en"
    parse_formats: List[str] = field(default_factory=lambda: [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y/%m/%d",
        "%Y.%m.%d",
    ])
    relative_patterns: Dict[str, re.Pattern] = field(default_factory=lambda: {
        "seconds_ago": re.compile(r"(\d+)\s*(?:sec|second|seconds)\s*ago", re.IGNORECASE),
        "minutes_ago": re.compile(r"(\d+)\s*(?:min|minute|minutes)\s*ago", re.IGNORECASE),
        "hours_ago": re.compile(r"(\d+)\s*(?:hr|hour|hours)\s*ago", re.IGNORECASE),
        "days_ago": re.compile(r"(\d+)\s*(?:day|days)\s*ago", re.IGNORECASE),
        "weeks_ago": re.compile(r"(\d+)\s*(?:week|weeks)\s*ago", re.IGNORECASE),
        "months_ago": re.compile(r"(\d+)\s*(?:month|months)\s*ago", re.IGNORECASE),
        "years_ago": re.compile(r"(\d+)\s*(?:year|years)\s*ago", re.IGNORECASE),
        "just_now": re.compile(r"just\s*now|moments?\s*ago", re.IGNORECASE),
        "today": re.compile(r"^today\s*(?:at)?", re.IGNORECASE),
        "yesterday": re.compile(r"^yesterday\s*(?:at)?", re.IGNORECASE),
        "tomorrow": re.compile(r"^tomorrow\s*(?:at)?", re.IGNORECASE),
        "this_week": re.compile(r"this\s+week", re.IGNORECASE),
        "last_week": re.compile(r"last\s+week", re.IGNORECASE),
        "next_week": re.compile(r"next\s+week", re.IGNORECASE),
    })


class DateNormalizer:
    def __init__(self, config: Optional[DateConfig] = None):
        self.config = config or DateConfig()
        self.base_time = self.config.relative_base or datetime.now(timezone.utc)
    
    def normalize(self, date_input: Union[str, datetime, None],
                  source_timezone: Optional[str] = None) -> NormalizedDate:
        """Normalize a date value to standard format."""
        if date_input is None:
            return NormalizedDate(
                original_value="",
                normalized_value=self.base_time,
            )
        
        if isinstance(date_input, datetime):
            result = NormalizedDate(
                original_value=date_input.isoformat(),
                normalized_value=date_input,
            )
            if date_input.tzinfo:
                result.timezone = str(date_input.tzinfo)
            return result
        
        original_str = str(date_input).strip()
        result = NormalizedDate(original_value=original_str)
        
        if not original_str:
            result.normalized_value = self.base_time
            return result
        
        # Try parsing as relative date first
        relative = self._parse_relative(original_str)
        if relative:
            result.normalized_value = relative
            result.is_relative = True
            return result
        
        # Try absolute formats
        parsed = self._parse_absolute(original_str)
        if parsed:
            result.normalized_value = parsed
            if source_timezone:
                result.timezone = source_timezone
            return result
        
        # Fallback
        result.normalized_value = self.base_time
        return result
    
    def normalize_multiple(self, dates: List[Union[str, datetime, None]]) -> List[NormalizedDate]:
        """Normalize multiple date values."""
        return [self.normalize(d) for d in dates]
    
    def extract_dates_from_text(self, text: str) -> List[NormalizedDate]:
        """Extract all dates from text content."""
        dates = []
        
        # Try relative patterns
        for pattern_name, pattern in self.config.relative_patterns.items():
            matches = pattern.finditer(text)
            for match in matches:
                date_str = match.group(0)
                normalized = self.normalize(date_str)
                if normalized.is_relative or normalized.normalized_value != self.base_time:
                    dates.append(normalized)
        
        # Try absolute formats (common patterns)
        absolute_patterns = [
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b\d{2}/\d{2}/\d{4}\b",
            r"\b\d{2}-\d{2}-\d{4}\b",
            r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
        ]
        
        for pattern in absolute_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                date_str = match.group(0)
                normalized = self.normalize(date_str)
                if normalized.normalized_value != self.base_time:
                    dates.append(normalized)
        
        # Deduplicate
        seen = set()
        unique = []
        for d in dates:
            key = d.normalized_value.isoformat()
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique
    
    def _parse_relative(self, text: str) -> Optional[datetime]:
        """Parse relative date expressions."""
        text_lower = text.lower().strip()
        
        # Just now
        if self.config.relative_patterns["just_now"].search(text_lower):
            return self.base_time
        
        # Today
        today_match = self.config.relative_patterns["today"].search(text_lower)
        if today_match:
            time_part = text_lower.replace(today_match.group(0), "").strip()
            base = self.base_time.replace(hour=0, minute=0, second=0, microsecond=0)
            if time_part:
                time_parsed = self._parse_time(time_part)
                if time_parsed:
                    return base.replace(hour=time_parsed.hour, minute=time_parsed.minute)
            return base
        
        # Yesterday
        yesterday_match = self.config.relative_patterns["yesterday"].search(text_lower)
        if yesterday_match:
            time_part = text_lower.replace(yesterday_match.group(0), "").strip()
            base = (self.base_time - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if time_part:
                time_parsed = self._parse_time(time_part)
                if time_parsed:
                    return base.replace(hour=time_parsed.hour, minute=time_parsed.minute)
            return base
        
        # Tomorrow
        tomorrow_match = self.config.relative_patterns["tomorrow"].search(text_lower)
        if tomorrow_match:
            time_part = text_lower.replace(tomorrow_match.group(0), "").strip()
            base = (self.base_time + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            if time_part:
                time_parsed = self._parse_time(time_part)
                if time_parsed:
                    return base.replace(hour=time_parsed.hour, minute=time_parsed.minute)
            return base
        
        # X seconds/minutes/hours/days/weeks/months/years ago
        for unit, pattern in [
            ("seconds", "seconds_ago"),
            ("minutes", "minutes_ago"),
            ("hours", "hours_ago"),
            ("days", "days_ago"),
            ("weeks", "weeks_ago"),
            ("months", "months_ago"),
            ("years", "years_ago"),
        ]:
            match = self.config.relative_patterns[pattern].search(text_lower)
            if match:
                value = int(match.group(1))
                if unit == "seconds":
                    return self.base_time - timedelta(seconds=value)
                elif unit == "minutes":
                    return self.base_time - timedelta(minutes=value)
                elif unit == "hours":
                    return self.base_time - timedelta(hours=value)
                elif unit == "days":
                    return self.base_time - timedelta(days=value)
                elif unit == "weeks":
                    return self.base_time - timedelta(weeks=value)
                elif unit == "months":
                    return self.base_time - timedelta(days=value * 30)
                elif unit == "years":
                    return self.base_time - timedelta(days=value * 365)
        
        # This/last/next week
        if self.config.relative_patterns["this_week"].search(text_lower):
            return self.base_time - timedelta(days=self.base_time.weekday())
        if self.config.relative_patterns["last_week"].search(text_lower):
            return self.base_time - timedelta(days=self.base_time.weekday() + 7)
        if self.config.relative_patterns["next_week"].search(text_lower):
            return self.base_time + timedelta(days=7 - self.base_time.weekday())
        
        return None
    
    def _parse_time(self, text: str) -> Optional[datetime]:
        """Parse time from text."""
        time_patterns = [
            r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?",
            r"(\d{1,2})\s*(am|pm)",
        ]
        for pattern in time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if match.group(2) else 0
                ampm = match.group(3) if len(match.groups()) >= 3 else (match.group(2) if len(match.groups()) == 2 else None)
                if ampm:
                    ampm = ampm.lower()
                    if ampm == "pm" and hour != 12:
                        hour += 12
                    elif ampm == "am" and hour == 12:
                        hour = 0
                return datetime(2000, 1, 1, hour, minute)
        return None
    
    def _parse_absolute(self, text: str) -> Optional[datetime]:
        """Parse absolute date formats."""
        for fmt in self.config.parse_formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        return None
    
    def to_timezone(self, dt: datetime, target_tz: str = "UTC") -> datetime:
        """Convert datetime to target timezone."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        if target_tz == "UTC":
            return dt.astimezone(timezone.utc)
        
        # For other timezones, would need pytz or zoneinfo
        # Fallback to UTC
        return dt.astimezone(timezone.utc)
    
    def format_date(self, dt: datetime, format_type: str = "iso") -> str:
        """Format datetime for output."""
        if format_type == "iso":
            return dt.isoformat()
        elif format_type == "short":
            return dt.strftime("%Y-%m-%d")
        elif format_type == "long":
            return dt.strftime("%B %d, %Y")
        elif format_type == "relative":
            return self._format_relative(dt)
        return dt.isoformat()
    
    def _format_relative(self, dt: datetime) -> str:
        """Format datetime as relative string."""
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        
        diff = now - dt
        
        if diff < timedelta(minutes=1):
            return "just now"
        elif diff < timedelta(hours=1):
            mins = int(diff.total_seconds() / 60)
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff < timedelta(days=7):
            days = diff.days
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif diff < timedelta(days=30):
            weeks = diff.days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        elif diff < timedelta(days=365):
            months = diff.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = diff.days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"


def parse_date_string(text: str, config: Optional[DateConfig] = None) -> NormalizedDate:
    """Convenience function to parse a single date string."""
    normalizer = DateNormalizer(config)
    return normalizer.normalize(text)


def extract_dates(text: str, config: Optional[DateConfig] = None) -> List[NormalizedDate]:
    """Convenience function to extract all dates from text."""
    normalizer = DateNormalizer(config)
    return normalizer.extract_dates_from_text(text)