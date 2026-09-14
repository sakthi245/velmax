from __future__ import annotations

import ipaddress
import os
import re
import secrets
import string
import time
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Union, Pattern, Callable, Tuple
from urllib.parse import urlparse, urljoin
from ipaddress import IPv4Address, IPv6Address, IPv4Network, IPv6Network
import hashlib
import base64


class SecurityError(Exception):
    """Base exception for security-related errors."""
    pass


class SSRFProtectionError(SecurityError):
    """Raised when SSRF protection blocks a request."""
    pass


class InputValidationError(SecurityError):
    """Raised when input validation fails."""
    pass


class SecretNotFoundError(SecurityError):
    """Raised when a secret is not found."""
    pass


class SecurityConfig:
    """Central security configuration."""
    
    def __init__(
        self,
        # SSRF Protection
        enable_ssrf_protection: bool = True,
        allowed_ip_ranges: Optional[List[str]] = None,
        blocked_ip_ranges: Optional[List[str]] = None,
        block_private_ips: bool = True,
        block_loopback: bool = True,
        block_link_local: bool = True,
        block_multicast: bool = True,
        block_reserved: bool = True,
        allowed_ports: Optional[Set[int]] = None,
        blocked_ports: Optional[Set[int]] = None,
        # Input Validation
        max_url_length: int = 2048,
        max_header_size: int = 8192,
        max_body_size: int = 10 * 1024 * 1024,  # 10MB
        allowed_schemes: Set[str] = field(default_factory=lambda: {"http", "https"}),
        blocked_schemes: Set[str] = field(default_factory=lambda: {"file", "ftp", "gopher", "dict", "ldap", "telnet"}),
        # Secrets Management
        secrets_backend: str = "env",  # "env", "vault", "aws_secrets_manager", "azure_key_vault"
        secret_rotation_days: int = 90,
        # CORS
        cors_enabled: bool = True,
        cors_allowed_origins: Optional[List[str]] = None,
        cors_allowed_methods: List[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]),
        cors_allowed_headers: List[str] = field(default_factory=lambda: ["Content-Type", "Authorization", "X-Requested-With", "Accept", "Origin"]),
        cors_allow_credentials: bool = True,
        cors_max_age: int = 86400,
        # CSP
        csp_enabled: bool = True,
        csp_policy: Optional[str] = None,
        # Input Sanitization
        max_request_size: int = 10 * 1024 * 1024,
        max_header_count: int = 100,
        max_header_name_length: int = 256,
        max_header_value_length: int = 4096,
        strip_null_bytes: bool = True,
        normalize_unicode: bool = True,
    ):
        # SSRF Protection
        self.enable_ssrf_protection = enable_ssrf_protection
        self.allowed_ip_ranges = allowed_ip_ranges or []
        self.blocked_ip_ranges = blocked_ip_ranges or []
        self.block_private_ips = block_private_ips
        self.block_loopback = block_loopback
        self.block_link_local = block_link_local
        self.block_multicast = block_multicast
        self.block_reserved = block_reserved
        self.allowed_ports = allowed_ports or set()
        self.blocked_ports = blocked_ports or {22, 23, 25, 110, 143, 993, 995, 3306, 5432, 6379, 27017}
        
        # Input Validation
        self.max_url_length = max_url_length
        self.max_header_size = max_header_size
        self.max_body_size = max_body_size
        self.allowed_schemes = allowed_schemes
        self.blocked_schemes = blocked_schemes
        
        # Secrets
        self.secrets_backend = secrets_backend
        self.secret_rotation_days = secret_rotation_days
        
        # CORS
        self.cors_enabled = cors_enabled
        self.cors_allowed_origins = cors_allowed_origins or []
        self.cors_allowed_methods = cors_allowed_methods
        self.cors_allowed_headers = cors_allowed_headers
        self.cors_allow_credentials = cors_allow_credentials
        self.cors_max_age = cors_max_age
        
        # CSP
        self.csp_enabled = csp_enabled
        self.csp_policy = csp_policy or self._default_csp_policy()
        
        # Input Sanitization
        self.max_request_size = max_request_size
        self.max_header_count = max_header_count
        self.max_header_name_length = max_header_name_length
        self.max_header_value_length = max_header_value_length
        self.strip_null_bytes = strip_null_bytes
        self.normalize_unicode = normalize_unicode
    
    def _default_csp_policy(self) -> str:
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none';"
        )


# ============================================================================
# IP Address Validation & SSRF Protection
# ============================================================================

class IPValidator:
    """Validates IP addresses against allow/block lists and security policies."""
    
    # Private/Internal IP ranges (RFC 1918, RFC 4193, RFC 3927, etc.)
    PRIVATE_NETWORKS = [
        IPv4Network("10.0.0.0/8"),
        IPv4Network("172.16.0.0/12"),
        IPv4Network("192.168.0.0/16"),
        IPv6Network("fc00::/7"),  # Unique Local Addresses (ULA)
    ]
    
    LOOPBACK_NETWORKS = [
        IPv4Network("127.0.0.0/8"),
        IPv6Network("::1/128"),
    ]
    
    LINK_LOCAL_NETWORKS = [
        IPv4Network("169.254.0.0/16"),
        IPv6Network("fe80::/10"),
    ]
    
    MULTICAST_NETWORKS = [
        IPv4Network("224.0.0.0/4"),
        IPv6Network("ff00::/8"),
    ]
    
    RESERVED_NETWORKS = [
        IPv4Network("0.0.0.0/8"),
        IPv4Network("100.64.0.0/10"),  # CGNAT
        IPv4Network("192.0.0.0/24"),   # IETF Protocol Assignments
        IPv4Network("192.0.2.0/24"),   # TEST-NET-1
        IPv4Network("198.51.100.0/24"), # TEST-NET-2
        IPv4Network("203.0.113.0/24"), # TEST-NET-3
        IPv4Network("240.0.0.0/4"),    # Reserved
        IPv4Network("255.255.255.255/32"), # Broadcast
    ]
    
    def __init__(self, config: SecurityConfig):
        self.config = config
        self._allowed_networks: List[Union[IPv4Network, IPv6Network]] = []
        self._blocked_networks: List[Union[IPv4Network, IPv6Network]] = []
        self._compile_networks()
    
    def _compile_networks(self):
        """Compile allowed and blocked network ranges."""
        # Add default blocked networks
        if self.config.block_private_ips:
            self._blocked_networks.extend(self.PRIVATE_NETWORKS)
        if self.config.block_loopback:
            self._blocked_networks.extend(self.LOOPBACK_NETWORKS)
        if self.config.block_link_local:
            self._blocked_networks.extend(self.LINK_LOCAL_NETWORKS)
        if self.config.block_multicast:
            self._blocked_networks.extend(self.MULTICAST_NETWORKS)
        if self.config.block_reserved:
            self._blocked_networks.extend(self.RESERVED_NETWORKS)
        
        # Add custom blocked ranges
        for cidr in self.config.blocked_ip_ranges:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
                self._blocked_networks.append(net)
            except ValueError:
                pass
        
        # Add allowed ranges
        for cidr in self.config.allowed_ip_ranges:
            try:
                net = ipaddress.ip_network(cidr, strict=False)
                self._allowed_networks.append(net)
            except ValueError:
                pass
    
    def validate_ip(self, ip_str: str) -> bool:
        """Validate an IP address against allow/block lists."""
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        
        # Check allowed first (explicit allow overrides block)
        if self._allowed_networks:
            if not any(ip in net for net in self._allowed_networks):
                return False
        
        # Check blocked
        if any(ip in net for net in self._blocked_networks):
            return False
        
        # Check port if applicable
        # Note: This validator only checks IP, port checking is separate
        return True
    
    def validate_url(self, url: str) -> bool:
        """Validate a URL against security policies."""
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        
        # Check scheme
        if parsed.scheme not in self.config.allowed_schemes:
            return False
        if parsed.scheme in self.config.blocked_schemes:
            return False
        
        # Check URL length
        if len(url) > self.config.max_url_length:
            return False
        
        # Validate hostname/IP
        hostname = parsed.hostname or ""
        if not hostname:
            return False
        
        # Resolve and check IP
        try:
            ip = ipaddress.ip_address(hostname)
            if not self.validate_ip(str(ip)):
                return False
        except ValueError:
            # Not an IP, check if it's a valid hostname
            if not self._is_valid_hostname(hostname):
                return False
        
        # Check port
        port = parsed.port
        if port is not None:
            if self.config.allowed_ports and port not in self.config.allowed_ports:
                return False
            if port in self.config.blocked_ports:
                return False
        
        # Check for suspicious patterns
        if self._is_suspicious_url(url):
            return False
        
        return True
    
    def _is_valid_hostname(self, hostname: str) -> bool:
        """Validate hostname format."""
        if len(hostname) > 253:
            return False
        if hostname.endswith('.'):
            hostname = hostname[:-1]
        return all(
            re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$', label)
            for label in hostname.split('.')
        )
    
    def _is_suspicious_url(self, url: str) -> bool:
        """Check for suspicious URL patterns."""
        suspicious_patterns = [
            r'[a-zA-Z0-9]{32,}',  # Long random strings
            r'\.(exe|bat|sh|php|jsp|asp)(\?|$)',  # Executable extensions
            r'(javascript|data|vbscript):',  # Dangerous schemes
            r'(%[0-9a-fA-F]{2}){5,}',  # Heavy URL encoding
        ]
        return any(re.search(p, url, re.I) for p in suspicious_patterns)


# ============================================================================
# Input Sanitization
# ============================================================================

class InputSanitizer:
    """Sanitizes and validates input data."""
    
    # Dangerous patterns for XSS/injection
    XSS_PATTERNS = [
        (re.compile(r'<script\b[^>]*>.*?</script>', re.I | re.S), ''),
        (re.compile(r'javascript:', re.I), ''),
        (re.compile(r'on\w+\s*=', re.I), ''),
        (re.compile(r'expression\s*\(', re.I), ''),
        (re.compile(r'vbscript:', re.I), ''),
        (re.compile(r'onload\s*=', re.I), ''),
        (re.compile(r'onerror\s*=', re.I), ''),
        (re.compile(r'onclick\s*=', re.I), ''),
        (re.compile(r'<iframe', re.I), ''),
        (re.compile(r'<object', re.I), ''),
        (re.compile(r'<embed', re.I), ''),
        (re.compile(r'<applet', re.I), ''),
    ]
    
    SQL_INJECTION_PATTERNS = [
        (re.compile(r'\b(union|select|insert|update|delete|drop|create|alter|exec|execute)\b', re.I), ''),
        (re.compile(r'(--|#|;)\s*$', re.I), ''),
        (re.compile(r'(\'|\")\s*(or|and)\s*\1\s*=\s*\1', re.I), ''),
    ]
    
    CMD_INJECTION_PATTERNS = [
        (re.compile(r'[;&|`$]{1,2}\s*'), ''),
        (re.compile(r'\b(cat|ls|cp|mv|rm|wget|curl|nc|bash|sh|python|perl)\s'), ''),
    ]
    
    PATH_TRAVERSAL_PATTERNS = [
        (re.compile(r'\.\./'), ''),
        (re.compile(r'\.\.\\'), ''),
        (re.compile(r'%2e%2e%2f', re.I), ''),
        (re.compile(r'%2e%2e/', re.I), ''),
        (re.compile(r'\.\.%2f', re.I), ''),
    ]
    
    def __init__(self):
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Pre-compile regex patterns."""
        self._xss_re = [(re.compile(p[0].pattern, p[0].flags), p[1]) for p in self.XSS_PATTERNS]
        self._sql_re = [(re.compile(p[0].pattern, p[0].flags), p[1]) for p in self.SQL_INJECTION_PATTERNS]
        self._cmd_re = [(re.compile(p[0].pattern, p[0].flags), p[1]) for p in self.CMD_INJECTION_PATTERNS]
        self._path_re = [(re.compile(p[0].pattern, p[0].flags), p[1]) for p in self.PATH_TRAVERSAL_PATTERNS]
    
    def sanitize_html(self, text: str, strip_tags: bool = True) -> str:
        """Sanitize HTML content."""
        if not isinstance(text, str):
            return str(text)
        
        # Remove null bytes
        text = text.replace('\x00', '')
        
        if strip_tags:
            # Remove HTML tags
            text = re.sub(r'<[^>]+>', '', text)
        else:
            # Apply XSS filters
            for pattern, replacement in self._xss_re:
                text = pattern.sub(replacement, text)
        
        return text
    
    def sanitize_sql(self, text: str) -> str:
        """Sanitize SQL input."""
        if not isinstance(text, str):
            return str(text)
        
        for pattern, replacement in self._sql_re:
            text = pattern.sub(replacement, text)
        return text
    
    def sanitize_command(self, text: str) -> str:
        """Sanitize command injection attempts."""
        if not isinstance(text, str):
            return str(text)
        
        for pattern, replacement in self._cmd_re:
            text = pattern.sub(replacement, text)
        return text
    
    def sanitize_path(self, path: str) -> str:
        """Prevent path traversal."""
        if not isinstance(path, str):
            return str(path)
        
        # Normalize path
        path = os.path.normpath(path)
        
        # Remove path traversal attempts
        for pattern, replacement in self._path_re:
            path = pattern.sub(replacement, path)
        
        # Ensure path doesn't escape base directory
        path = os.path.normpath(path)
        if path.startswith('..') or os.path.isabs(path):
            raise SecurityError(f"Path traversal attempt detected: {path}")
        
        return path
    
    def sanitize_filename(self, filename: str, allow_unicode: bool = False) -> str:
        """Sanitize filename for safe storage."""
        if not isinstance(filename, str):
            filename = str(filename)
        
        # Remove path components
        filename = os.path.basename(filename)
        
        # Remove null bytes
        filename = filename.replace('\x00', '')
        
        # Remove dangerous characters
        filename = re.sub(r'[<>:"|?*\x00-\x1f]', '_', filename)
        
        # Limit length
        max_len = 255
        if len(filename) > max_len:
            name, ext = os.path.splitext(filename)
            filename = name[:max_len - len(ext)] + ext
        
        # Ensure not empty
        if not filename or filename in ('.', '..'):
            filename = 'unnamed'
        
        return filename
    
    def sanitize_for_log(self, text: str, max_length: int = 1000) -> str:
        """Sanitize text for safe logging."""
        if not isinstance(text, str):
            text = str(text)
        
        # Remove control characters except newlines/tabs
        text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text)
        
        # Truncate
        if len(text) > max_length:
            text = text[:max_length] + '... [truncated]'
        
        return text
    
    def validate_json(self, data: Any, max_depth: int = 10, max_keys: int = 1000) -> bool:
        """Validate JSON structure for safety."""
        def _check(obj: Any, depth: int) -> bool:
            if depth > max_depth:
                return False
            if isinstance(obj, dict):
                if len(obj) > max_keys:
                    return False
                return all(isinstance(k, str) and len(k) < 256 for k in obj.keys()) and \
                       all(_check(v, depth + 1) for v in obj.values())
            elif isinstance(obj, list):
                if len(obj) > max_keys:
                    return False
                return all(_check(item, depth + 1) for item in obj)
            elif isinstance(obj, str):
                return len(obj) < 100000  # Max string length
            return True
        
        return _check(data, 0)
    
    def sanitize_text(self, text: str) -> str:
        """Basic text sanitization."""
        if not isinstance(text, str):
            return str(text)
        # Remove null bytes
        return text.replace('\x00', '')


# ============================================================================
# Secrets Management
# ============================================================================

class SecretManager:
    """Manages secrets with support for multiple backends and rotation."""
    
    def __init__(self, config: SecurityConfig):
        self.config = config
        self._cache: Dict[str, str] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = 300  # 5 minutes
        self._rotation_timestamps: Dict[str, float] = {}
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get a secret value."""
        # Check cache first
        if key in self._cache:
            if time.time() - self._cache_times.get(key, 0) < 300:
                return self._cache[key]
        
        value = None
        
        if self.config.secrets_backend == "env":
            value = os.environ.get(key)
        elif self.config.secrets_backend == "file":
            # Read from secrets file
            value = self._read_from_file(key)
        elif self.config.secrets_backend == "vault":
            # HashiCorp Vault integration
            value = self._get_from_vault(key)
        elif self.config.secrets_backend == "aws_secrets_manager":
            # AWS Secrets Manager
            value = self._get_from_aws(key)
        elif self.config.secrets_backend == "azure_key_vault":
            # Azure Key Vault
            value = self._get_from_azure(key)
        
        if value is not None:
            self._cache[key] = value
            self._cache_times[key] = time.time()
            return value
        
        return default
    
    def set_secret(self, key: str, value: str) -> None:
        """Set a secret (for testing or runtime configuration)."""
        self._cache[key] = value
        self._cache_times[key] = time.time()
    
    def rotate_secret(self, key: str) -> str:
        """Generate and store a new secret."""
        new_secret = self.generate_secret()
        self._cache[key] = new_secret
        self._cache_times[key] = time.time()
        # In production, would also update the backend
        return new_secret
    
    def generate_secret(self, length: int = 32) -> str:
        """Generate a cryptographically secure random secret."""
        alphabet = string.ascii_letters + string.digits + "-_"
        return ''.join(secrets.choice(alphabet) for _ in range(length))
    
    def generate_api_key(self, prefix: str = "sk") -> str:
        """Generate an API key with prefix."""
        return f"{prefix}_{secrets.token_urlsafe(32)}"
    
    def hash_secret(self, secret: str) -> str:
        """Hash a secret for storage."""
        return hashlib.sha256(secret.encode()).hexdigest()
    
    def verify_secret(self, secret: str, hashed: str) -> bool:
        """Verify a secret against its hash."""
        return secrets.compare_digest(self.hash_secret(secret), hashed)
    
    def needs_rotation(self, key: str) -> bool:
        """Check if a secret needs rotation."""
        if key not in self._rotation_timestamps:
            return True
        age = time.time() - self._rotation_timestamps[key]
        return age > (self.config.secret_rotation_days * 86400)
    
    def needs_rotation_any(self) -> List[str]:
        """Get list of keys that need rotation."""
        return [k for k in self._cache.keys() if self.needs_rotation(k)]
    
    # Private backend methods
    def _read_from_file(self, key: str) -> Optional[str]:
        """Read secret from file."""
        try:
            with open(f"/run/secrets/{key}", "r") as f:
                return f.read().strip()
        except Exception:
            return None
    
    def _get_from_vault(self, key: str) -> Optional[str]:
        """Get secret from HashiCorp Vault."""
        # Placeholder for Vault integration
        return None
    
    def _get_from_aws(self, key: str) -> Optional[str]:
        """Get secret from AWS Secrets Manager."""
        # Placeholder for AWS integration
        return None
    
    def _get_from_azure(self, key: str) -> Optional[str]:
        """Get secret from Azure Key Vault."""
        # Placeholder for Azure integration
        return None


# ============================================================================
# CORS Handler
# ============================================================================

class CORSHandler:
    """Handles CORS headers and preflight requests."""
    
    def __init__(self, config: SecurityConfig):
        self.config = config
    
    def get_cors_headers(self, origin: str, method: str, request_headers: str = "") -> Dict[str, str]:
        """Generate CORS headers for a response."""
        headers = {}
        
        if not self.config.cors_enabled:
            return headers
        
        origin_allowed = self._is_origin_allowed(origin)
        
        if origin_allowed:
            headers["Access-Control-Allow-Origin"] = origin
            if self.config.cors_allow_credentials:
                headers["Access-Control-Allow-Credentials"] = "true"
        elif "*" in self.config.cors_allowed_origins:
            headers["Access-Control-Allow-Origin"] = "*"
        
        headers["Access-Control-Allow-Methods"] = ", ".join(self.config.cors_allowed_methods)
        headers["Access-Control-Allow-Headers"] = ", ".join(self.config.cors_allowed_headers)
        headers["Access-Control-Max-Age"] = str(self.config.cors_max_age)
        
        return headers
    
    def _is_origin_allowed(self, origin: str) -> bool:
        if not origin:
            return False
        if "*" in self.config.cors_allowed_origins:
            return True
        return origin in self.config.cors_allowed_origins
    
    def handle_preflight(self, origin: str, method: str, headers: str) -> Dict[str, str]:
        """Handle OPTIONS preflight request."""
        if not self._is_origin_allowed(origin):
            return {}
        
        if method.upper() not in [m.upper() for m in self.config.cors_allowed_methods]:
            return {}
        
        requested_headers = [h.strip() for h in self.config.cors_allowed_headers]
        requested = [h.strip().lower() for h in headers.split(",")] if headers else []
        allowed = all(h.lower() in [rh.lower() for rh in self.config.cors_allowed_headers] for h in requested)
        
        if not allowed:
            return {}
        
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": ", ".join(self.config.cors_allowed_methods),
            "Access-Control-Allow-Headers": ", ".join(self.config.cors_allowed_headers),
            "Access-Control-Max-Age": str(self.config.cors_max_age),
            "Access-Control-Allow-Credentials": "true" if self.config.cors_allow_credentials else "false",
        }


# ============================================================================
# Content Security Policy
# ============================================================================

class CSPBuilder:
    """Builds Content Security Policy headers."""
    
    DIRECTIVES = [
        'default-src', 'script-src', 'style-src', 'img-src',
        'font-src', 'connect-src', 'media-src', 'object-src',
        'child-src', 'frame-ancestors', 'form-action', 'base-uri',
        'object-src', 'frame-src', 'worker-src', 'manifest-src',
        'prefetch-src', 'script-src-elem', 'script-src-attr',
        'style-src-elem', 'style-src-attr', 'navigate-to',
        'report-to', 'report-uri'
    ]
    
    def __init__(self, policy: Optional[str] = None):
        self.directives: Dict[str, List[str]] = {}
        if policy:
            self.parse(policy)
    
    def parse(self, policy: str):
        """Parse a CSP policy string."""
        for directive in policy.split(';'):
            directive = directive.strip()
            if not directive:
                continue
            parts = directive.split(None, 1)
            if len(parts) == 2:
                self.directives[parts[0]] = [v.strip() for v in parts[1].split()]
            elif parts[0]:
                self.directives[parts[0]] = []
    
    def add(self, directive: str, *values: str):
        """Add values to a directive."""
        if directive not in self.directives:
            self.directives[directive] = []
        for value in values:
            if value not in self.directives[directive]:
                self.directives[directive].append(value)
    
    def remove(self, directive: str, value: str = None):
        """Remove a value from a directive."""
        if directive in self.directives:
            if value:
                if value in self.directives[directive]:
                    self.directives[directive].remove(value)
            else:
                del self.directives[directive]
    
    def build(self) -> str:
        """Build CSP header value."""
        parts = []
        for directive, values in self.directives.items():
            if values:
                parts.append(f"{directive} {' '.join(values)}")
            else:
                parts.append(directive)
        return "; ".join(parts) + ";"
    
    @classmethod
    def strict(cls) -> 'CSPBuilder':
        """Create a strict CSP."""
        csp = cls()
        csp.add('default-src', "'self'")
        csp.add('script-src', "'self'")
        csp.add('style-src', "'self'")
        csp.add('img-src', "'self'", 'data:', 'https:')
        csp.add('font-src', "'self'")
        csp.add('connect-src', "'self'")
        csp.add('frame-ancestors', "'none'")
        csp.add('base-uri', "'self'")
        csp.add('form-action', "'self'")
        csp.add('object-src', "'none'")
        return csp
    
    @classmethod
    def permissive(cls) -> 'CSPBuilder':
        """Create a permissive CSP for development."""
        csp = cls()
        csp.add('default-src', "'self'", "'unsafe-inline'", "'unsafe-eval'", 'https:', 'data:')
        csp.add('img-src', "'self'", 'data:', 'https:', 'blob:')
        csp.add('font-src', "'self'", 'data:', 'https:')
        csp.add('connect-src', "'self'", 'https:', 'wss:')
        csp.add('frame-ancestors', "'self'")
        return csp
    
    @classmethod
    def from_string(cls, policy: str) -> 'CSPBuilder':
        return cls(policy)


# ============================================================================
# Security Middleware / Helpers
# ============================================================================

class SecurityHeaders:
    """Generate security headers for HTTP responses."""
    
    DEFAULT_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
    
    def __init__(self, config: SecurityConfig):
        self.config = config
    
    def get_headers(self, csp: Optional[str] = None) -> Dict[str, str]:
        """Get all security headers."""
        headers = dict(self.DEFAULT_HEADERS)
        
        if self.config.csp_enabled:
            csp = self.config.csp_policy or CSPBuilder.strict().build()
            headers["Content-Security-Policy"] = csp
        
        if self.config.cors_enabled:
            # CORS headers added separately
            pass
        
        return headers


# ============================================================================
# High-level Security Manager
# ============================================================================

class SecurityManager:
    """Central security manager coordinating all security features."""
    
    def __init__(self, config: Optional[SecurityConfig] = None):
        self.config = config or SecurityConfig()
        self.ip_validator = IPValidator(self.config)
        self.sanitizer = InputSanitizer()
        self.secret_manager = SecretManager(self.config)
        self.cors_handler = CORSHandler(self.config)
        self.csp_builder = CSPBuilder(self.config.csp_policy)
        self.metrics = {
            "blocked_requests": 0,
            "blocked_ssrf": 0,
            "blocked_xss": 0,
            "sanitized_inputs": 0,
        }
    
    def validate_request(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
    ) -> Tuple[bool, List[str]]:
        """Validate an incoming request."""
        errors = []
        
        # Validate URL
        if not self.validate_url(url):
            errors = ["Invalid or blocked URL"]
            self.metrics["blocked_requests"] += 1
            return False, errors
        
        # Check request size
        if body and len(body) > self.config.max_body_size:
            errors.append(f"Request body exceeds maximum size of {self.config.max_body_size} bytes")
        
        # Check headers
        if headers:
            if len(headers) > self.config.max_header_count:
                errors.append(f"Too many headers (max {self.config.max_header_count})")
            for name, value in headers.items():
                if len(name) > self.config.max_header_name_length:
                    errors.append(f"Header name too long: {name}")
                if len(value) > self.config.max_header_value_length:
                    errors.append(f"Header value too long: {name}")
        
        # Check body size
        if body and len(body) > self.config.max_body_size:
            errors.append(f"Body exceeds maximum size of {self.config.max_body_size} bytes")
        
        return len(errors) == 0, errors
    
    def validate_url(self, url: str) -> bool:
        """Validate a URL against security policies."""
        if not self.config.enable_ssrf_protection:
            return True
        return self.ip_validator.validate_url(url)
    
    def _scan_for_threats(self, body: bytes):
        """Scan request body for threats."""
        try:
            text = body.decode('utf-8', errors='ignore')
        except Exception:
            return
        
        # Check for XSS
        if re.search(r'<script|javascript:|on\w+\s*=', body, re.I):
            self.metrics["blocked_xss"] += 1
            raise SecurityError("Potential XSS detected")
        
        # Check for SQL injection
        if re.search(r'\b(union|select|insert|update|delete|drop)\b', body, re.I):
            self.metrics["blocked_xss"] += 1
            raise SecurityError("Potential SQL injection detected")
    
    def sanitize_input(self, data: Any, context: str = "default") -> Any:
        """Sanitize input based on context."""
        if isinstance(data, str):
            if context == "html":
                return self.sanitizer.sanitize_html(data)
            elif context == "sql":
                return self.sanitizer.sanitize_sql(data)
            elif context == "command":
                return self.sanitizer.sanitize_command(data)
            elif context == "path":
                return self.sanitizer.sanitize_path(data)
            elif context == "filename":
                return self.sanitizer.sanitize_filename(data)
            else:
                return self.sanitizer.sanitize_text(data)
        elif isinstance(data, dict):
            return {k: self.sanitize_input(v, context) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.sanitize_input(v, context) for v in data]
        return data
    
    def get_cors_headers(self, origin: str, method: str, request_headers: str = "") -> Dict[str, str]:
        return self.cors_handler.get_cors_headers(origin, method, request_headers)
    
    def handle_preflight(self, origin: str, method: str, headers: str) -> Dict[str, str]:
        return self.cors_handler.handle_preflight(origin, method, headers)
    
    def get_csp_header(self) -> str:
        return self.csp_builder.build()
    
    def get_secret(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.secret_manager.get_secret(key, default)
    
    def set_secret(self, key: str, value: str) -> None:
        self.secret_manager.set_secret(key, value)
    
    def rotate_secret(self, key: str) -> str:
        return self.secret_manager.rotate_secret(key)
    
    def generate_api_key(self, prefix: str = "sk") -> str:
        return self.secret_manager.generate_api_key(prefix)
    
    def get_metrics(self) -> Dict[str, int]:
        return self.metrics.copy()
    
    def record_sanitization(self):
        self.metrics["sanitized_inputs"] += 1


# ============================================================================
# Convenience Functions
# ============================================================================

_default_security_manager: Optional[SecurityManager] = None


def get_security_manager(config: Optional[SecurityConfig] = None) -> SecurityManager:
    """Get or create the default security manager."""
    global _default_security_manager
    if _default_security_manager is None:
        _default_security_manager = SecurityManager(config)
    return _default_security_manager


def sanitize_input(data: Any, context: str = "default") -> Any:
    """Convenience function to sanitize input."""
    manager = get_security_manager()
    return manager.sanitize_input(data, context)


def validate_url(url: str, config: Optional[SecurityConfig] = None) -> bool:
    """Validate a URL against security policies."""
    manager = get_security_manager(SecurityConfig() if config is None else config)
    return manager.validate_url(url)


def sanitize_html(text: str, strip_tags: bool = True) -> str:
    """Sanitize HTML content."""
    sanitizer = InputSanitizer()
    return sanitizer.sanitize_html(text, strip_tags)


def sanitize_sql(text: str) -> str:
    """Sanitize SQL input."""
    sanitizer = InputSanitizer()
    return sanitizer.sanitize_sql(text)


def sanitize_path(path: str) -> str:
    """Sanitize file path."""
    sanitizer = InputSanitizer()
    return sanitizer.sanitize_path(path)


def generate_api_key(prefix: str = "sk") -> str:
    """Generate a secure API key."""
    manager = SecretManager(SecurityConfig())
    return manager.generate_api_key(prefix)


def generate_secret(length: int = 32) -> str:
    """Generate a secure random secret."""
    manager = SecretManager(SecurityConfig())
    return manager.generate_secret(length)


# ============================================================================
# Export all public classes and functions
# ============================================================================

__all__ = [
    # Config
    "SecurityConfig",
    # Exceptions
    "SecurityError",
    "SSRFProtectionError",
    "InputValidationError",
    "SecretNotFoundError",
    # Core classes
    "IPValidator",
    "InputSanitizer",
    "SecretManager",
    "CORSHandler",
    "CSPBuilder",
    "SecurityHeaders",
    "SecurityManager",
    # Convenience functions
    "get_security_manager",
    "sanitize_input",
    "validate_url",
    "sanitize_html",
    "sanitize_sql",
    "sanitize_path",
    "generate_api_key",
    "generate_secret",
]


if __name__ == "__main__":
    # Demo usage
    config = SecurityConfig(
        enable_ssrf_protection=True,
        block_private_ips=True,
        allowed_ip_ranges=["10.0.0.0/8", "192.168.0.0/16"],
    )
    
    manager = SecurityManager(config)
    
    # Test URL validation
    test_urls = [
        "https://example.com",
        "http://localhost:8080",
        "http://192.168.1.1",
        "http://10.0.0.1",
        "file:///etc/passwd",
        "javascript:alert(1)",
    ]
    
    for url in test_urls:
        valid = SecurityManager(SecurityConfig(
            enable_ssrf_protection=True, 
            block_private_ips=True
        )).validate_url(url)
        print(f"{url}: {'VALID' if valid else 'BLOCKED'}")
    
    # Test sanitization
    print("\n--- Sanitization Tests ---")
    print(sanitize_html("<script>alert(1)</script>Hello"))
    print(sanitize_sql("1; DROP TABLE users"))
    print(sanitize_path("../../../etc/passwd"))
    print(generate_api_key())
    print(generate_secret(16))