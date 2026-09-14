from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import random
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from playwright.async_api import BrowserContext, Page


@dataclass
class StealthConfig:
    enabled: bool = True
    navigator: bool = True
    webdriver: bool = True
    chrome_runtime: bool = True
    permissions: bool = True
    plugins: bool = True
    languages: bool = True
    platform: bool = True
    hardware_concurrency: bool = True
    device_memory: bool = True
    screen: bool = True
    timezone: bool = True
    locale: bool = True
    color_scheme: bool = True
    media_codecs: bool = True
    webrtc: bool = True
    fonts: bool = True
    canvas: bool = True
    webgl: bool = True
    audio_context: bool = True
    battery: bool = True
    touch: bool = True
    mouse: bool = True
    randomize_fingerprint: bool = True
    fingerprint_seed: Optional[str] = None
    custom_scripts: List[str] = field(default_factory=list)
    # Fingerprint rotation settings
    rotation_strategy: str = "per_session"  # per_session, per_request, per_domain, timed
    rotation_interval_minutes: int = 30


@dataclass
class BrowserFingerprint:
    user_agent: str
    platform: str
    language: str
    languages: List[str]
    hardware_concurrency: int
    device_memory: int
    screen_width: int
    screen_height: int
    color_depth: int
    pixel_ratio: float
    timezone: str
    timezone_offset: int
    webgl_vendor: str
    webgl_renderer: str
    canvas_fingerprint: str
    audio_fingerprint: str
    fonts: List[str]
    plugins: List[Dict[str, Any]]
    permissions: Dict[str, str]
    battery: Dict[str, Any]
    touch_points: int
    webdriver: bool = False
    
    # Enhanced fingerprint fields
    webgl_extensions: List[str] = field(default_factory=list)
    webgl_parameters: Dict[str, Any] = field(default_factory=dict)
    audio_sample_rate: float = 44100
    audio_channel_count: int = 2
    canvas_noise: str = ""
    webgl_unmasked_vendor: str = ""
    webgl_unmasked_renderer: str = ""
    client_rects: List[Dict[str, float]] = field(default_factory=list)
    media_devices: List[Dict[str, Any]] = field(default_factory=list)
    speech_voices: List[Dict[str, Any]] = field(default_factory=list)
    webdriver: bool = False


class FingerprintGenerator:
    PLATFORMS = [
        "Win32", "Win64", "MacIntel", "Linux x86_64", "Linux armv7l", "Linux aarch64"
    ]

    LANGUAGES = [
        ["en-US", "en"], ["en-GB", "en"], ["de-DE", "de"], ["fr-FR", "fr"],
        ["es-ES", "es"], ["it-IT", "it"], ["pt-BR", "pt"], ["ru-RU", "ru"],
        ["ja-JP", "ja"], ["ko-KR", "ko"], ["zh-CN", "zh"],
    ]

    TIMEZONES = [
        "America/New_York", "America/Los_Angeles", "America/Chicago", "America/Denver",
        "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Rome",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Seoul", "Asia/Singapore",
        "Australia/Sydney", "Pacific/Auckland",
    ]

    WEBGL_VENDORS = [
        "Google Inc. (NVIDIA)", "Google Inc. (AMD)", "Google Inc. (Intel)",
        "Mozilla (NVIDIA)", "Mozilla (AMD)", "Mozilla (Intel)",
        "Apple (Apple GPU)", "Microsoft (DirectX)",
    ]

    WEBGL_RENDERERS = [
        "ANGLE (NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0)",
        "ANGLE (Intel Iris Xe Graphics Direct3D11 vs_5_0 ps_5_0)",
        "Apple GPU",
        "Mesa Intel UHD Graphics",
        "Mesa AMD Radeon",
    ]

    COMMON_FONTS = [
        "Arial", "Arial Black", "Comic Sans MS", "Courier New", "Georgia",
        "Impact", "Times New Roman", "Trebuchet MS", "Verdana", "Webdings",
        "Helvetica", "Helvetica Neue", "Roboto", "Open Sans", "Lato",
        "Montserrat", "Source Sans Pro", "Oswald", "Raleway", "Ubuntu",
    ]

    COMMON_PLUGINS = [
        {"name": "Chrome PDF Plugin", "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
        {"name": "Chrome PDF Viewer", "filename": "mhjfbmdgcfkbbpaeojofohoefgiehjai", "description": ""},
        {"name": "Native Client", "filename": "internal-nacl-plugin", "description": ""},
    ]
    
    # WebGL extensions and parameters
    WEBGL_EXTENSIONS = [
        "ANGLE_instanced_arrays",
        "EXT_blend_minmax",
        "EXT_color_buffer_half_float",
        "EXT_disjoint_timer_query",
        "EXT_float_blend",
        "EXT_frag_depth",
        "EXT_shader_texture_lod",
        "EXT_texture_compression_bptc",
        "EXT_texture_compression_rgtc",
        "EXT_texture_filter_anisotropic",
        "OES_element_index_uint",
        "OES_standard_derivatives",
        "OES_texture_float",
        "OES_texture_float_linear",
        "OES_texture_half_float",
        "OES_texture_half_float_linear",
        "OES_vertex_array_object",
        "WEBGL_color_buffer_float",
        "WEBGL_compressed_texture_astc",
        "WEBGL_compressed_texture_etc",
        "WEBGL_compressed_texture_s3tc",
        "WEBGL_compressed_texture_s3tc_srgb",
        "WEBGL_debug_renderer_info",
        "WEBGL_debug_shaders",
        "WEBGL_depth_texture",
        "WEBGL_draw_buffers",
        "WEBGL_lose_context",
    ]
    
    WEBGL_PARAMETERS = {
        "ALIASED_LINE_WIDTH_RANGE": [1, 1],
        "ALIASED_POINT_SIZE_RANGE": [1, 1024],
        "ALPHA_BITS": 8,
        "BLUE_BITS": 8,
        "DEPTH_BITS": 24,
        "GREEN_BITS": 8,
        "MAX_3D_TEXTURE_SIZE": 2048,
        "MAX_COMBINED_TEXTURE_IMAGE_UNITS": 32,
        "MAX_CUBE_MAP_TEXTURE_SIZE": 16384,
        "MAX_FRAGMENT_UNIFORM_VECTORS": 1024,
        "MAX_RENDERBUFFER_SIZE": 16384,
        "MAX_TEXTURE_IMAGE_UNITS": 16,
        "MAX_TEXTURE_SIZE": 16384,
        "MAX_VARYING_VECTORS": 30,
        "MAX_VERTEX_ATTRIBS": 16,
        "MAX_VERTEX_TEXTURE_IMAGE_UNITS": 16,
        "MAX_VERTEX_UNIFORM_VECTORS": 1024,
        "MAX_VIEWPORT_DIMS": [16384, 16384],
        "RED_BITS": 8,
        "RENDERBUFFER_ALPHA_SIZE": 8,
        "RENDERBUFFER_BLUE_SIZE": 8,
        "RENDERBUFFER_DEPTH_SIZE": 24,
        "RENDERBUFFER_GREEN_SIZE": 8,
        "RENDERBUFFER_RED_SIZE": 8,
        "RENDERBUFFER_STENCIL_SIZE": 8,
        "STENCIL_BITS": 8,
        "SUBPIXEL_BITS": 4,
        "TEXTURE_2D": True,
        "UNPACK_ALIGNMENT": 4,
        "UNPACK_COLORSPACE_CONVERSION_WEBGL": 37443,
        "UNPACK_FLIP_Y_WEBGL": True,
        "UNPACK_PREMULTIPLY_ALPHA_WEBGL": True,
    }
    
    # Audio context profiles
    AUDIO_PROFILES = [
        {"sample_rate": 44100, "channel_count": 2, "channel_interpretation": "speakers"},
        {"sample_rate": 48000, "channel_count": 2, "channel_interpretation": "discrete"},
        {"sample_rate": 44100, "channel_count": 1, "channel_interpretation": "speakers"},
        {"sample_rate": 48000, "channel_count": 1, "channel_interpretation": "discrete"},
    ]
    
    # Media devices profiles
    MEDIA_DEVICES_PROFILES = [
        {
            "videoinput": [
                {"deviceId": "default", "kind": "videoinput", "label": "Integrated Camera", "groupId": "group1"},
            ],
            "audioinput": [
                {"deviceId": "default", "kind": "audioinput", "label": "Microphone Array", "groupId": "group2"},
            ],
            "audiooutput": [
                {"deviceId": "default", "kind": "audiooutput", "label": "Speakers", "groupId": "group3"},
            ],
        },
        {
            "videoinput": [
                {"deviceId": "camera1", "kind": "videoinput", "label": "USB Camera", "groupId": "group1"},
            ],
            "audioinput": [
                {"deviceId": "mic1", "kind": "audioinput", "label": "External Microphone", "groupId": "group2"},
            ],
            "audiooutput": [
                {"deviceId": "speaker1", "kind": "audiooutput", "label": "Headphones", "groupId": "group3"},
            ],
        },
    ]
    
    # Speech synthesis voices
    SPEECH_VOICES = [
        {"voiceURI": "Microsoft David", "name": "David", "lang": "en-US", "localService": True, "default": True},
        {"voiceURI": "Microsoft Zira", "name": "Zira", "lang": "en-US", "localService": True, "default": False},
        {"voiceURI": "Microsoft Mark", "name": "Mark", "lang": "en-US", "localService": True, "default": False},
        {"voiceURI": "Google US English", "name": "Google US English", "lang": "en-US", "localService": False, "default": False},
        {"voiceURI": "Microsoft Anna", "name": "Anna", "lang": "en-US", "localService": True, "default": False},
    ]
    
    def __init__(self, seed: Optional[str] = None):
        self.seed = seed or str(int(time.time() * 1000000))
        self._rng = random.Random(self.seed)

    def generate(self) -> BrowserFingerprint:
        platform = self._rng.choice(self.PLATFORMS)
        lang_data = self._rng.choice(self.LANGUAGES)

        is_mobile = "arm" in platform.lower() or "android" in platform.lower()
        is_mac = "Mac" in platform

        if is_mobile:
            hardware_concurrency = self._rng.choice([4, 6, 8])
            device_memory = self._rng.choice([4, 6, 8])
        elif is_mac:
            hardware_concurrency = self._rng.choice([8, 10, 12])
            device_memory = self._rng.choice([8, 16, 32])
        else:
            hardware_concurrency = self._rng.choice([4, 6, 8, 12, 16])
            device_memory = self._rng.choice([8, 16, 32, 64])

        if is_mobile:
            screen_width = self._rng.choice([375, 390, 412, 414, 428])
            screen_height = self._rng.choice([667, 736, 844, 896, 926])
        elif is_mac:
            screen_width = self._rng.choice([1440, 1512, 1680, 2560, 2880])
            screen_height = self._rng.choice([900, 982, 1050, 1600, 1800])
        else:
            screen_width = self._rng.choice([1366, 1440, 1536, 1920, 2560])
            screen_height = self._rng.choice([768, 900, 864, 1080, 1440])

        color_depth = 24
        pixel_ratio = self._rng.choice([1.0, 1.25, 1.5, 2.0, 3.0])

        timezone = self._rng.choice(self.TIMEZONES)
        tz_offset = self._get_timezone_offset(timezone)

        webgl_vendor = self._rng.choice(self.WEBGL_VENDORS)
        webgl_renderer = self._rng.choice(self.WEBGL_RENDERERS)

        canvas_fp = self._generate_canvas_fingerprint()
        audio_fp = self._generate_audio_fingerprint()

        fonts = self._rng.sample(self.COMMON_FONTS, k=self._rng.randint(15, min(25, len(self.COMMON_FONTS))))
        plugins = self.COMMON_PLUGINS.copy()
        if self._rng.random() > 0.3:
            plugins.append({
                "name": "Widevine Content Decryption Module",
                "filename": "widevinecdmadapter",
                "description": "Enables Widevine licenses for playback of HTML audio/video",
            })

        return BrowserFingerprint(
            user_agent=self._generate_user_agent(platform, is_mobile),
            platform=platform,
            language=lang_data[0],
            languages=lang_data,
            hardware_concurrency=hardware_concurrency,
            device_memory=device_memory,
            screen_width=screen_width,
            screen_height=screen_height,
            color_depth=color_depth,
            pixel_ratio=pixel_ratio,
            timezone=timezone,
            timezone_offset=tz_offset,
            webgl_vendor=webgl_vendor,
            webgl_renderer=webgl_renderer,
            canvas_fingerprint=canvas_fp,
            audio_fingerprint=audio_fp,
            fonts=fonts,
            plugins=plugins,
            permissions={
                "geolocation": self._rng.choice(["granted", "denied", "prompt"]),
                "notifications": self._rng.choice(["granted", "denied", "prompt"]),
                "camera": self._rng.choice(["granted", "denied", "prompt"]),
                "microphone": self._rng.choice(["granted", "denied", "prompt"]),
            },
            battery={
                "charging": self._rng.choice([True, False]),
                "level": round(self._rng.uniform(0.2, 1.0), 2),
                "chargingTime": 0 if self._rng.choice([True, False]) else self._rng.randint(0, 3600),
                "dischargingTime": self._rng.randint(0, 7200),
            },
            touch_points=self._rng.randint(1, 10) if is_mobile else 0,
            # Enhanced fields
            webgl_extensions=self._rng.sample(self.WEBGL_EXTENSIONS, k=self._rng.randint(15, 25)),
            webgl_parameters=self._rng.choice([self.WEBGL_PARAMETERS]),
            audio_sample_rate=self._rng.choice([44100, 48000, 96000]),
            audio_channel_count=self._rng.choice([1, 2]),
            canvas_noise=self._generate_canvas_noise(),
            webgl_unmasked_vendor=webgl_vendor,
            webgl_unmasked_renderer=webgl_renderer,
            client_rects=self._generate_client_rects(),
            media_devices=self._generate_media_devices(),
            speech_voices=self._generate_speech_voices(),
        )

    def _get_timezone_offset(self, timezone: str) -> int:
        offsets = {
            "America/New_York": -300, "America/Los_Angeles": -480,
            "America/Chicago": -360, "America/Denver": -420,
            "Europe/London": 0, "Europe/Paris": 60, "Europe/Berlin": 60, "Europe/Rome": 60,
            "Asia/Tokyo": 540, "Asia/Shanghai": 480, "Asia/Seoul": 540, "Asia/Singapore": 480,
            "Australia/Sydney": 600, "Pacific/Auckland": 720,
        }
        return offsets.get(timezone, 0)

    def _generate_user_agent(self, platform: str, is_mobile: bool) -> str:
        chrome_version = f"{random.randint(115, 125)}.0.{random.randint(5000, 6500)}.{random.randint(100, 200)}"
        webkit_version = "537.36"

        if "Win" in platform:
            os_part = f"Windows NT {random.choice(['10.0', '11.0'])}"
            if "64" in platform:
                os_part += "; Win64; x64"
        elif "Mac" in platform:
            os_part = f"Macintosh; Intel Mac OS X 10_{random.randint(13, 15)}_{random.randint(0, 7)}"
        elif "Linux" in platform:
            if is_mobile:
                os_part = "Linux armv8l"
            else:
                os_part = "X11; Linux x86_64"
        else:
            os_part = "X11; Linux x86_64"

        if is_mobile:
            return (f"Mozilla/5.0 ({os_part}) AppleWebKit/{webkit_version} "
                    f"(KHTML, like Gecko) Chrome/{chrome_version} Mobile Safari/{webkit_version}")
        else:
            return (f"Mozilla/5.0 ({os_part}) AppleWebKit/{webkit_version} "
                    f"(KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version}")

    def _generate_canvas_fingerprint(self) -> str:
        chars = "0123456789abcdef"
        return "".join(self._rng.choice(chars) for _ in range(64))

    def _generate_audio_fingerprint(self) -> str:
        chars = "0123456789abcdef"
        return "".join(self._rng.choice(chars) for _ in range(32))

    def _generate_canvas_noise(self) -> str:
        """Generate subtle canvas noise for fingerprinting."""
        chars = "0123456789abcdef"
        return "".join(self._rng.choice(chars) for _ in range(16))

    def _generate_client_rects(self) -> List[Dict[str, float]]:
        """Generate realistic client rects for fingerprinting."""
        rects = []
        for _ in range(self._rng.randint(3, 8)):
            x = round(self._rng.uniform(0, 1920), 2)
            y = round(self._rng.uniform(0, 1080), 2)
            width = round(self._rng.uniform(50, 800), 2)
            height = round(self._rng.uniform(20, 400), 2)
            rects.append({
                "x": x, "y": y,
                "width": width, "height": height,
                "top": y, "left": x,
                "right": x + width, "bottom": y + height,
            })
        return rects

    def _generate_media_devices(self) -> List[Dict[str, Any]]:
        """Generate realistic media devices list."""
        return self._rng.choice(self.MEDIA_DEVICES_PROFILES)

    def _generate_speech_voices(self) -> List[Dict[str, Any]]:
        """Generate realistic speech synthesis voices list."""
        num_voices = self._rng.randint(3, 6)
        voices = self._rng.sample(self.SPEECH_VOICES, k=min(num_voices, len(self.SPEECH_VOICES)))
        # Add some variation
        for voice in voices:
            voice["default"] = voice.get("default", False)
        return voices


class FingerprintRotator:
    """Manages fingerprint rotation per session with configurable strategies."""
    
    def __init__(
        self,
        rotation_strategy: str = "per_session",  # per_session, per_request, per_domain, timed
        rotation_interval_minutes: int = 30,
        base_seed: Optional[str] = None,
    ):
        self.rotation_strategy = rotation_strategy
        self.rotation_interval_minutes = rotation_interval_minutes
        self.base_seed = base_seed or str(int(time.time() * 1000000))
        self._session_fingerprints: Dict[str, Tuple[BrowserFingerprint, float]] = {}
        self._domain_fingerprints: Dict[str, Tuple[BrowserFingerprint, float]] = {}
        self._last_rotation: Dict[str, float] = {}
        self._base_generator = FingerprintGenerator(self.base_seed)
        self._rotation_count: Dict[str, int] = {}
        
    def get_fingerprint(
        self,
        session_id: Optional[str] = None,
        domain: Optional[str] = None,
        force_new: bool = False,
    ) -> BrowserFingerprint:
        """Get a fingerprint for the given session/domain with rotation logic."""
        now = time.time()
        
        if self.rotation_strategy == "per_session" and session_id:
            return self._get_session_fingerprint(session_id, force_new)
        elif self.rotation_strategy == "per_domain" and domain:
            return self._get_domain_fingerprint(domain, force_new)
        elif self.rotation_strategy == "timed":
            return self._get_timed_fingerprint(session_id or "default", now, force_new)
        elif self.rotation_strategy == "per_request":
            return self._generate_new_fingerprint()
        else:
            return self._get_session_fingerprint(session_id or "default", force_new)
    
    def _get_session_fingerprint(self, session_id: str, force_new: bool) -> BrowserFingerprint:
        if session_id not in self._session_fingerprints or force_new:
            fp = self._generate_session_fingerprint(session_id)
            self._session_fingerprints[session_id] = (fp, time.time())
            self._rotation_count[session_id] = self._rotation_count.get(session_id, 0) + 1
        elif self._should_rotate(session_id):
            fp = self._generate_session_fingerprint(session_id)
            self._session_fingerprints[session_id] = (fp, time.time())
            self._rotation_count[session_id] += 1
        return self._session_fingerprints[session_id][0]
    
    def _get_domain_fingerprint(self, domain: str, force_new: bool) -> BrowserFingerprint:
        if domain not in self._domain_fingerprints or force_new:
            fp = self._generate_domain_fingerprint(domain)
            self._domain_fingerprints[domain] = (fp, time.time())
        elif self._should_rotate_domain(domain):
            fp = self._generate_domain_fingerprint(domain)
            self._domain_fingerprints[domain] = (fp, time.time())
        return self._domain_fingerprints[domain][0]
    
    def _get_timed_fingerprint(self, key: str, now: float, force_new: bool) -> BrowserFingerprint:
        last_rotation = self._last_rotation.get(key, 0)
        if force_new or now - last_rotation > self.rotation_interval_minutes * 60:
            fp = self._generate_session_fingerprint(key)
            self._last_rotation[key] = now
            return fp
        if key not in self._session_fingerprints:
            fp = self._generate_session_fingerprint(key)
            self._session_fingerprints[key] = (fp, now)
            return fp
        return self._session_fingerprints[key][0]
    
    def _should_rotate(self, session_id: str) -> bool:
        """Determine if fingerprint should rotate based on usage."""
        count = self._rotation_count.get(session_id, 0)
        # Rotate every 10-20 requests with some randomness
        threshold = 10 + (hash(session_id) % 10)
        return count >= threshold
    
    def _should_rotate_domain(self, domain: str) -> bool:
        return False  # Domain fingerprints are more stable
    
    def _generate_session_fingerprint(self, session_id: str) -> BrowserFingerprint:
        """Generate a fingerprint with session-specific seed."""
        session_seed = f"{self.base_seed}:{session_id}"
        generator = FingerprintGenerator(session_seed)
        return generator.generate()
    
    def _generate_domain_fingerprint(self, domain: str) -> BrowserFingerprint:
        """Generate a fingerprint with domain-specific seed."""
        domain_seed = f"{self.base_seed}:domain:{domain}"
        generator = FingerprintGenerator(domain_seed)
        return generator.generate()
    
    def _generate_new_fingerprint(self) -> BrowserFingerprint:
        return self._base_generator.generate()
    
    def rotate_fingerprint(self, session_id: Optional[str] = None, domain: Optional[str] = None) -> BrowserFingerprint:
        """Force rotation of fingerprint for session or domain."""
        if session_id:
            self._session_fingerprints.pop(session_id, None)
            self._rotation_count.pop(session_id, None)
            return self.get_fingerprint(session_id=session_id, force_new=True)
        elif domain:
            self._domain_fingerprints.pop(domain, None)
            return self.get_fingerprint(domain=domain, force_new=True)
        return self._generate_new_fingerprint()
    
    def get_rotation_stats(self) -> Dict[str, Any]:
        return {
            "strategy": self.rotation_strategy,
            "session_count": len(self._session_fingerprints),
            "domain_count": len(self._domain_fingerprints),
            "total_rotations": sum(self._rotation_count.values()),
        }


class StealthManager:
    def __init__(self, config: Optional[StealthConfig] = None):
        self.config = config or StealthConfig()
        # Use FingerprintRotator for per-session rotation
        self.rotator = FingerprintRotator(
            rotation_strategy=self.config.rotation_strategy if hasattr(self.config, 'rotation_strategy') else "per_session",
            rotation_interval_minutes=self.config.rotation_interval_minutes if hasattr(self.config, 'rotation_interval_minutes') else 30,
            base_seed=self.config.fingerprint_seed,
        )
        self._fingerprint: Optional[BrowserFingerprint] = None
        self._scripts_cache: Dict[str, str] = {}
        import logging
        self.logger = logging.getLogger("stealth")

    def get_fingerprint(self, session_id: Optional[str] = None, domain: Optional[str] = None) -> BrowserFingerprint:
        """Get a fingerprint for the given session/domain with rotation."""
        return self.rotator.get_fingerprint(session_id=session_id, domain=domain)

    def rotate_fingerprint(self, session_id: Optional[str] = None, domain: Optional[str] = None) -> BrowserFingerprint:
        """Force rotation of fingerprint for session or domain."""
        return self.rotator.rotate_fingerprint(session_id=session_id, domain=domain)

    def get_rotation_stats(self) -> Dict[str, Any]:
        return self.rotator.get_rotation_stats()

    def generate_stealth_script(self, fingerprint: Optional[BrowserFingerprint] = None) -> str:
        fp = fingerprint or self.get_fingerprint()
        scripts = []

        if self.config.webdriver:
            scripts.append(self._script_hide_webdriver())

        if self.config.navigator:
            scripts.append(self._script_navigator(fp))

        if self.config.chrome_runtime:
            scripts.append(self._script_chrome_runtime())

        if self.config.permissions:
            scripts.append(self._script_permissions(fp))

        if self.config.plugins:
            scripts.append(self._script_plugins(fp))

        if self.config.languages:
            scripts.append(self._script_languages(fp))

        if self.config.platform:
            scripts.append(self._script_platform(fp))

        if self.config.hardware_concurrency:
            scripts.append(self._script_hardware_concurrency(fp))

        if self.config.device_memory:
            scripts.append(self._script_device_memory(fp))

        if self.config.screen:
            scripts.append(self._script_screen(fp))

        if self.config.timezone:
            scripts.append(self._script_timezone(fp))

        if self.config.locale:
            scripts.append(self._script_locale(fp))

        if self.config.color_scheme:
            scripts.append(self._script_color_scheme())

        if self.config.media_codecs:
            scripts.append(self._script_media_codecs())

        if self.config.webrtc:
            scripts.append(self._script_webrtc())

        if self.config.fonts:
            scripts.append(self._script_fonts(fp))

        if self.config.canvas:
            scripts.append(self._script_canvas(fp))

        if self.config.webgl:
            scripts.append(self._script_webgl(fp))

        if self.config.audio_context:
            scripts.append(self._script_audio_context(fp))

        if self.config.battery:
            scripts.append(self._script_battery(fp))

        if self.config.touch:
            scripts.append(self._script_touch(fp))

        for custom_script in self.config.custom_scripts:
            scripts.append(custom_script)

        return "\n".join(scripts)

    async def apply_to_context(self, context: BrowserContext, fingerprint: Optional[BrowserFingerprint] = None):
        script = self.generate_stealth_script(fingerprint)
        await context.add_init_script(script)

    async def apply_to_page(self, page: Page, fingerprint: Optional[BrowserFingerprint] = None):
        script = self.generate_stealth_script(fingerprint)
        await page.add_init_script(script)

    def _script_hide_webdriver(self) -> str:
        return """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            delete navigator.__proto__.webdriver;
        """

    def _script_navigator(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(navigator, 'platform', {{ get: () => '{fp.platform}' }});
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp.hardware_concurrency} }});
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp.device_memory} }});
            Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {fp.touch_points} }});
        """

    def _script_chrome_runtime(self) -> str:
        return """
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: { isInstalled: false },
            };
        """

    def _script_permissions(self, fp: BrowserFingerprint) -> str:
        perms = json.dumps(fp.permissions)
        return f"""
            const originalQuery = navigator.permissions.query;
            navigator.permissions.query = function(parameters) {{
                const perm = {perms}[parameters.name];
                if (perm) {{
                    return Promise.resolve({{ state: perm, onchange: null }});
                }}
                return originalQuery(parameters);
            }};
        """

    def _script_plugins(self, fp: BrowserFingerprint) -> str:
        plugins_json = json.dumps(fp.plugins)
        return f"""
            Object.defineProperty(navigator, 'plugins', {{
                get: () => {{
                    const plugins = {plugins_json};
                    const pluginArray = [];
                    plugins.forEach(p => {{
                        pluginArray.push({{
                            name: p.name,
                            filename: p.filename,
                            description: p.description,
                            length: 1,
                            0: {{ type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' }},
                        }});
                    }});
                    pluginArray.item = function(index) {{ return this[index]; }};
                    pluginArray.namedItem = function(name) {{
                        for (let p of this) {{ if (p.name === name) return p; }}
                        return null;
                    }};
                    pluginArray.refresh = function() {{}};
                    return pluginArray;
                }},
            }});
        """

    def _script_languages(self, fp: BrowserFingerprint) -> str:
        langs = json.dumps(fp.languages)
        return f"""
            Object.defineProperty(navigator, 'language', {{ get: () => '{fp.language}' }});
            Object.defineProperty(navigator, 'languages', {{ get: () => {langs} }});
        """

    def _script_platform(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(navigator, 'platform', {{ get: () => '{fp.platform}' }});
        """

    def _script_hardware_concurrency(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => {fp.hardware_concurrency} }});
        """

    def _script_device_memory(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(navigator, 'deviceMemory', {{ get: () => {fp.device_memory} }});
        """

    def _script_screen(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(screen, 'width', {{ get: () => {fp.screen_width} }});
            Object.defineProperty(screen, 'height', {{ get: () => {fp.screen_height} }});
            Object.defineProperty(screen, 'colorDepth', {{ get: () => {fp.color_depth} }});
            Object.defineProperty(screen, 'pixelDepth', {{ get: () => {fp.color_depth} }});
            Object.defineProperty(window, 'devicePixelRatio', {{ get: () => {fp.pixel_ratio} }});
        """

    def _script_timezone(self, fp: BrowserFingerprint) -> str:
        return f"""
            Date.prototype.getTimezoneOffset = function() {{ return {fp.timezone_offset}; }};
            Intl.DateTimeFormat.prototype.resolvedOptions = function() {{
                return {{ timeZone: '{fp.timezone}' }};
            }};
        """

    def _script_locale(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(navigator, 'language', {{ get: () => '{fp.language}' }});
        """

    def _script_color_scheme(self) -> str:
        return """
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            Object.defineProperty(mediaQuery, 'matches', { get: () => false });
            Object.defineProperty(mediaQuery, 'media', { get: () => '(prefers-color-scheme: light)' });
        """

    def _script_media_codecs(self) -> str:
        return """
            const originalCanPlayType = HTMLMediaElement.prototype.canPlayType;
            HTMLMediaElement.prototype.canPlayType = function(type) {
                if (type.includes('h264') || type.includes('avc1') || type.includes('vp9')) {
                    return 'probably';
                }
                return originalCanPlayType.apply(this, arguments);
            };
        """

    def _script_webrtc(self) -> str:
        return """
            window.RTCPeerConnection = window.RTCPeerConnection || function() {
                return {
                    createOffer: () => Promise.resolve({ sdp: '', type: 'offer' }),
                    createAnswer: () => Promise.resolve({ sdp: '', type: 'answer' }),
                    setLocalDescription: () => Promise.resolve(),
                    setRemoteDescription: () => Promise.resolve(),
                    addIceCandidate: () => Promise.resolve(),
                    onicecandidate: null,
                };
            };
        """

    def _script_fonts(self, fp: BrowserFingerprint) -> str:
        fonts_json = json.dumps(fp.fonts)
        return f"""
            const fonts = {fonts_json};
            const originalMeasureText = CanvasRenderingContext2D.prototype.measureText;
            CanvasRenderingContext2D.prototype.measureText = function(text) {{
                const metrics = originalMeasureText.apply(this, arguments);
                return metrics;
            }};
            document.fonts = {{
                ready: Promise.resolve(),
                check: (font, text) => fonts.some(f => font.includes(f)),
                load: () => Promise.resolve(),
            }};
        """

    def _script_canvas(self, fp: BrowserFingerprint) -> str:
        canvas_noise = getattr(fp, 'canvas_noise', '')
        return f"""
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function(type, quality) {{
                if (type === 'image/png' && this.width > 0 && this.height > 0) {{
                    const ctx = this.getContext('2d');
                    if (ctx) {{
                        const imgData = ctx.getImageData(0, 0, this.width, this.height);
                        // Add subtle canvas noise for fingerprint consistency
                        const noise = '{canvas_noise}';
                        for (let i = 0; i < imgData.data.length; i += 4) {{
                            const noiseVal = parseInt(noise.substr((i/4) % noise.length, 1), 16);
                            imgData.data[i] = (imgData.data[i] + noiseVal) % 256;
                            imgData.data[i+1] = (imgData.data[i+1] + noiseVal) % 256;
                            imgData.data[i+2] = (imgData.data[i+2] + noiseVal) % 256;
                        }}
                        ctx.putImageData(imgData, 0, 0);
                    }}
                }}
                return originalToDataURL.apply(this, arguments);
            }};
            const originalGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function(type, attrs) {{
                const ctx = originalGetContext.apply(this, arguments);
                if (type === '2d') {{
                    const originalFillText = ctx.fillText;
                    ctx.fillText = function(text, x, y, maxWidth) {{
                        return originalFillText.apply(this, arguments);
                    }};
                }}
                return ctx;
            }};
        """

    def _script_webgl(self, fp: BrowserFingerprint) -> str:
        extensions_json = json.dumps(getattr(fp, 'webgl_extensions', []))
        params_json = json.dumps(getattr(fp, 'webgl_parameters', {}))
        unmasked_vendor = getattr(fp, 'webgl_unmasked_vendor', fp.webgl_vendor)
        unmasked_renderer = getattr(fp, 'webgl_unmasked_renderer', fp.webgl_renderer)
        return f"""
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                const params = {params_json};
                if (params.hasOwnProperty(parameter)) {{
                    return params[parameter];
                }}
                if (parameter === 37445) {{ return '{fp.webgl_vendor}'; }}
                if (parameter === 37446) {{ return '{fp.webgl_renderer}'; }}
                return getParameter.apply(this, arguments);
            }};
            const getExtension = WebGLRenderingContext.prototype.getExtension;
            WebGLRenderingContext.prototype.getExtension = function(name) {{
                const extensions = {extensions_json};
                if (extensions.includes(name)) {{
                    return {{}};
                }}
                if (name === 'WEBGL_debug_renderer_info') {{
                    return {{
                        UNMASKED_VENDOR_WEBGL: 37445,
                        UNMASKED_RENDERER_WEBGL: 37446,
                    }};
                }}
                return getExtension.apply(this, arguments);
            }};
            // Override unmasked vendor/renderer
            const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(p) {{
                if (p === 37445) return '{unmasked_vendor}';
                if (p === 37446) return '{unmasked_renderer}';
                return getParameterOrig.call(this, p);
            }};
        """

    def _script_audio_context(self, fp: BrowserFingerprint) -> str:
        sample_rate = getattr(fp, 'audio_sample_rate', 44100)
        channel_count = getattr(fp, 'audio_channel_count', 2)
        # Use ord() for Python string (fp.audio_fingerprint is a Python string)
        audio_fp_char_code = ord(fp.audio_fingerprint[0]) if fp.audio_fingerprint else 440
        return f"""
            const originalCreateOscillator = AudioContext.prototype.createOscillator;
            AudioContext.prototype.createOscillator = function() {{
                const osc = originalCreateOscillator.apply(this, arguments);
                const originalStart = osc.start;
                osc.start = function() {{
                    this.frequency.value = {audio_fp_char_code % 100 + 440};
                    return originalStart.apply(this, arguments);
                }};
                return osc;
            }};
            const originalAudioContext = window.AudioContext;
            window.AudioContext = function(options) {{
                const ctx = new originalAudioContext(options);
                const originalCreateOscillator = ctx.createOscillator;
                ctx.createOscillator = function() {{
                    const osc = originalCreateOscillator.apply(this, arguments);
                    const originalStart = osc.start;
                    osc.start = function() {{
                        this.frequency.value = {audio_fp_char_code % 100 + 440};
                        return originalStart.apply(this, arguments);
                    }};
                    return osc;
                }};
                // Override sample rate and channel count
                Object.defineProperty(ctx, 'sampleRate', {{ get: () => {sample_rate} }});
                Object.defineProperty(ctx, 'destination', {{
                    get: () => {{
                        const dest = originalAudioContext.prototype.destination;
                        Object.defineProperty(dest, 'channelCount', {{ get: () => {channel_count} }});
                        return dest;
                    }}
                }});
                return ctx;
            }};
        """

    def _script_battery(self, fp: BrowserFingerprint) -> str:
        battery = json.dumps(fp.battery)
        return f"""
            const batteryData = {battery};
            navigator.getBattery = function() {{
                return Promise.resolve(batteryData);
            }};
        """

    def _script_touch(self, fp: BrowserFingerprint) -> str:
        return f"""
            Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {fp.touch_points} }});
            Object.defineProperty(navigator, 'msMaxTouchPoints', {{ get: () => {fp.touch_points} }});
        """

    def generate_cloudflare_script(self, fingerprint: Optional[BrowserFingerprint] = None) -> str:
        """Generate script to detect and handle Cloudflare Turnstile challenges."""
        fp = fingerprint or self.get_fingerprint()
        return f"""
            // Cloudflare Turnstile detection and handling
            (function() {{
                const originalFetch = window.fetch;
                const originalXHROpen = XMLHttpRequest.prototype.open;
                const originalXHRSend = XMLHttpRequest.prototype.send;
                
                // Detect Cloudflare challenge page
                function isCloudflareChallenge() {{
                    return document.title.includes('Just a moment') ||
                           document.body.innerHTML.includes('challenge-platform') ||
                           document.body.innerHTML.includes('cf-challenge') ||
                           window.location.pathname.includes('/cdn-cgi/challenge') ||
                           document.querySelector('form#challenge-form') !== null;
                }}
                
                // Detect Turnstile widget
                function detectTurnstile() {{
                    return window.turnstile !== undefined ||
                           document.querySelector('.cf-turnstile') !== null ||
                           document.querySelector('[data-sitekey]') !== null;
                }}
                
                // Auto-solve Turnstile (manual fallback trigger)
                function handleTurnstile() {{
                    if (detectTurnstile()) {{
                        console.log('Turnstile detected, waiting for manual solve...');
                        // Wait for cf_clearance cookie
                        return new Promise((resolve) => {{
                            const checkCookie = setInterval(() => {{
                                if (document.cookie.includes('cf_clearance')) {{
                                    clearInterval(checkCookie);
                                    resolve(true);
                                }}
                            }}, 1000);
                            
                            // Timeout after 5 minutes
                            setTimeout(() => {{
                                clearInterval(checkCookie);
                                resolve(false);
                            }}, 300000);
                        }});
                    }}
                    return Promise.resolve(false);
                }}
                
                // Monitor for challenge completion
                async function waitForChallengeComplete() {{
                    if (isCloudflareChallenge()) {{
                        console.log('Cloudflare challenge detected, waiting...');
                        await handleTurnstile();
                        // Wait for redirect
                        await new Promise(resolve => setTimeout(resolve, 2000));
                        if (!isCloudflareChallenge()) {{
                            console.log('Challenge passed!');
                            return true;
                        }}
                    }}
                    return false;
                }}
                
                // Export for external use
                window.__cfDetector = {{
                    isChallenge: isCloudflareChallenge,
                    detectTurnstile,
                    waitForChallenge: waitForChallengeComplete,
                }};
                
                // Auto-check on page load
                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', waitForChallengeComplete);
                }} else {{
                    waitForChallengeComplete();
                }}
            }})();
        """

    def generate_captcha_script(self, fingerprint: Optional[BrowserFingerprint] = None) -> str:
        """Generate script for manual CAPTCHA fallback handling."""
        return """
            // Manual CAPTCHA fallback handler
            (function() {
                // Common CAPTCHA selectors
                const CAPTCHA_SELECTORS = [
                    'iframe[src*="recaptcha"]',
                    'iframe[src*="hcaptcha"]',
                    '.g-recaptcha',
                    '.h-captcha',
                    '#captcha',
                    '.captcha',
                    '[data-captcha]',
                    'iframe[title*="recaptcha"]',
                    'iframe[title*="hcaptcha"]',
                ];
                
                function detectCaptcha() {
                    for (const selector of CAPTCHA_SELECTORS) {
                        if (document.querySelector(selector)) {
                            return true;
                        }
                    }
                    return false;
                }
                
                async function waitForCaptchaSolve(timeoutMs = 300000) {
                    const start = Date.now();
                    while (Date.now() - start < timeoutMs) {
                        if (!detectCaptcha()) {
                            console.log('CAPTCHA solved!');
                            return true;
                        }
                        await new Promise(r => setTimeout(r, 1000));
                    }
                    console.log('CAPTCHA solve timeout');
                    return false;
                }
                
                // Export for external use
                window.__captchaHandler = {
                    detect: detectCaptcha,
                    waitForSolve: waitForCaptchaSolve,
                };
                
                // Auto-detect on load
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', () => {
                        if (detectCaptcha()) {
                            console.log('CAPTCHA detected, waiting for manual solve...');
                            waitForCaptchaSolve();
                        }
                    });
                } else if (detectCaptcha()) {
                    console.log('CAPTCHA detected, waiting for manual solve...');
                    waitForCaptchaSolve();
                }
            })();
        """

    async def wait_for_cloudflare_challenge(self, page: Page, timeout: int = 300000) -> bool:
        """Wait for Cloudflare challenge to complete (manual solve)."""
        try:
            start_time = time.time()
            while time.time() - start_time < timeout:
                # Check for Cloudflare challenge
                is_challenge = await page.evaluate("""
                    () => document.title.includes('Just a moment') ||
                          document.body.innerHTML.includes('challenge-platform') ||
                          document.body.innerHTML.includes('cf-challenge') ||
                          window.location.pathname.includes('/cdn-cgi/challenge')
                """)
                
                if not is_challenge:
                    # Check for Turnstile
                    has_turnstile = await page.evaluate("""
                        () => window.turnstile !== undefined ||
                              document.querySelector('.cf-turnstile') !== null
                    """)
                    
                    if has_turnstile:
                        # Wait for cf_clearance cookie
                        await page.wait_for_function(
                            "() => document.cookie.includes('cf_clearance')",
                            timeout=300000
                        )
                        return True
                    return True
                
                await asyncio.sleep(2)
            
            return False
        except Exception as e:
            self.logger.warning(f"Error waiting for Cloudflare challenge: {e}")
            return False

    async def wait_for_captcha_solve(self, page: Page, timeout: int = 300000) -> bool:
        """Wait for manual CAPTCHA solve.
        
        Args:
            page: Playwright page
            timeout: Timeout in milliseconds (default 5 minutes)
        """
        try:
            start_time = time.time()
            timeout_seconds = timeout / 1000.0
            while time.time() - start_time < timeout_seconds:
                has_captcha = await page.evaluate("""
                    () => {
                        const selectors = [
                            'iframe[src*="recaptcha"]',
                            'iframe[src*="hcaptcha"]',
                            '.g-recaptcha',
                            '.h-captcha',
                            '#captcha',
                            '.captcha',
                            '[data-captcha]',
                            '[data-testid="anomaly-modal"]',
                            '.anomaly-modal',
                            '.anomaly-modal__mask',
                            '#challenge-form',
                        ];
                        return selectors.some(s => document.querySelector(s) !== null);
                    }
                """)
                
                if not has_captcha:
                    return True
                
                await asyncio.sleep(2)
            
            return False
        except Exception as e:
            self.logger.warning(f"Error waiting for CAPTCHA: {e}")
            return False

    def _script_media_devices(self, fp: BrowserFingerprint) -> str:
        """Generate script to spoof media devices."""
        devices = getattr(fp, 'media_devices', {})
        devices_json = json.dumps(devices)
        return f"""
            const originalEnumerateDevices = navigator.mediaDevices.enumerateDevices;
            navigator.mediaDevices.enumerateDevices = async function() {{
                const devices = {devices_json};
                return devices;
            }};
        """

    def _script_speech_synthesis(self, fp: BrowserFingerprint) -> str:
        """Generate script to spoof speech synthesis voices."""
        voices = getattr(fp, 'speech_voices', [])
        voices_json = json.dumps(voices)
        return f"""
            const originalGetVoices = speechSynthesis.getVoices;
            speechSynthesis.getVoices = function() {{
                return {voices_json};
            }};
        """

    def _script_client_rects(self, fp: BrowserFingerprint) -> str:
        """Generate script to spoof client rects."""
        rects = getattr(fp, 'client_rects', [])
        rects_json = json.dumps(rects)
        return f"""
            const originalGetClientRects = Element.prototype.getClientRects;
            Element.prototype.getClientRects = function() {{
                if (this === document.documentElement) {{
                    return {rects_json}.map(r => {{
                        const rect = new DOMRect(r.x, r.y, r.width, r.height);
                        return rect;
                    }})}};
                }}
                return originalGetClientRects.call(this);
            }};
        """

    def generate_full_stealth_script(self, fingerprint: Optional[BrowserFingerprint] = None) -> str:
        """Generate complete stealth script including all anti-bot protections."""
        fp = fingerprint or self.get_fingerprint()
        scripts = []
        
        scripts.append(self.generate_stealth_script(fp))
        scripts.append(self.generate_cloudflare_script(fp))
        scripts.append(self.generate_captcha_script(fp))
        scripts.append(self._script_media_devices(fp))
        scripts.append(self._script_speech_synthesis(fp))
        scripts.append(self._script_client_rects(fp))
        
        return "\n".join(scripts)


# =============================================================================
# Turnstile / CAPTCHA Solver Integration
# =============================================================================

class TurnstileSolver:
    """Auto-solve Cloudflare Turnstile challenges using 2Captcha or Capsolver API."""
    
    PROVIDER_2CAPTCHA = "2captcha"
    PROVIDER_CAPSOLVER = "capsolver"
    
    def __init__(
        self,
        provider: str = PROVIDER_2CAPTCHA,
        api_key: str = "",
        page_timeout: int = 120000,
        poll_interval: int = 5000,
    ):
        self.provider = provider
        self.api_key = api_key
        self.page_timeout = page_timeout
        self.poll_interval = poll_interval
        
        if provider == self.PROVIDER_2CAPTCHA:
            self.api_url = "http://2captcha.com"
        elif provider == self.PROVIDER_CAPSOLVER:
            self.api_url = "https://api.capsolver.com"
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    async def solve_turnstile(
        self,
        page_url: str,
        sitekey: str,
        action: str = "",
        cdata: str = "",
        pagedata: str = "",
    ) -> Optional[str]:
        """Solve Turnstile challenge and return token."""
        if not self.api_key:
            return None
        
        try:
            if self.provider == self.PROVIDER_2CAPTCHA:
                return await self._solve_2captcha(page_url, sitekey, action, cdata, pagedata)
            elif self.provider == self.PROVIDER_CAPSOLVER:
                return await self._solve_capsolver(page_url, sitekey, action, cdata, pagedata)
        except Exception as e:
            return None
    
    async def _solve_2captcha(
        self,
        page_url: str,
        sitekey: str,
        action: str,
        cdata: str,
        pagedata: str,
    ) -> Optional[str]:
        """Solve using 2Captcha API."""
        import aiohttp
        
        # Submit task
        async with aiohttp.ClientSession() as session:
            # Submit
            submit_data = {
                "key": self.api_key,
                "method": "turnstile",
                "pageurl": page_url,
                "sitekey": sitekey,
                "json": 1,
            }
            if action:
                submit_data["action"] = action
            if cdata:
                submit_data["cdata"] = cdata
            if pagedata:
                submit_data["pagedata"] = pagedata
            
            async with session.post(f"{self.api_url}/in.php", data=submit_data) as resp:
                result = await resp.json()
                if result.get("status") != 1:
                    return None
                task_id = result.get("request")
            
            # Poll for result
            for _ in range(60):  # Max 5 minutes (60 * 5s)
                await asyncio.sleep(5)
                async with session.get(
                    f"{self.api_url}/res.php",
                    params={"key": self.api_key, "action": "get", "id": task_id, "json": 1}
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") != "CAPCHA_NOT_READY":
                        return None
        return None
    
    async def _solve_capsolver(
        self,
        page_url: str,
        sitekey: str,
        action: str,
        cdata: str,
        pagedata: str,
    ) -> Optional[str]:
        """Solve using Capsolver API."""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            # Create task
            task_data = {
                "clientKey": self.api_key,
                "task": {
                    "type": "AntiTurnstileTaskProxyLess",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                }
            }
            if action:
                task_data["task"]["action"] = action
            if cdata:
                task_data["task"]["cdata"] = cdata
            if pagedata:
                task_data["task"]["pagedata"] = pagedata
            
            async with session.post(f"{self.api_url}/createTask", json=task_data) as resp:
                result = await resp.json()
                if result.get("errorId") != 0:
                    return None
                task_id = result.get("taskId")
            
            # Poll for result
            for _ in range(60):
                await asyncio.sleep(5)
                async with session.post(
                    f"{self.api_url}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id}
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == "ready":
                        return result.get("solution", {}).get("token")
                    elif result.get("status") == "failed":
                        return None
        return None


class CaptchaSolver:
    """Solve reCAPTCHA and hCaptcha using 2Captcha or Capsolver API."""
    
    def __init__(
        self,
        provider: str = "2captcha",
        api_key: str = "",
        page_timeout: int = 120000,
    ):
        self.provider = provider
        self.api_key = api_key
        self.page_timeout = page_timeout
        
        if provider == "2captcha":
            self.api_url = "http://2captcha.com"
        elif provider == "capsolver":
            self.api_url = "https://api.capsolver.com"
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    async def solve_recaptcha_v2(
        self,
        page_url: str,
        sitekey: str,
        invisible: bool = False,
    ) -> Optional[str]:
        """Solve reCAPTCHA v2."""
        if not self.api_key:
            return None
        
        try:
            if self.provider == "2captcha":
                return await self._solve_recaptcha_2captcha(page_url, sitekey, invisible)
            elif self.provider == "capsolver":
                return await self._solve_recaptcha_capsolver(page_url, sitekey, invisible)
        except Exception:
            return None
    
    async def solve_hcaptcha(
        self,
        page_url: str,
        sitekey: str,
    ) -> Optional[str]:
        """Solve hCaptcha."""
        if not self.api_key:
            return None
        
        try:
            if self.provider == "2captcha":
                return await self._solve_hcaptcha_2captcha(page_url, sitekey)
            elif self.provider == "capsolver":
                return await self._solve_hcaptcha_capsolver(page_url, sitekey)
        except Exception:
            return None
    
    async def _solve_recaptcha_2captcha(
        self,
        page_url: str,
        sitekey: str,
        invisible: bool,
    ) -> Optional[str]:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            # Submit
            submit_data = {
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": sitekey,
                "pageurl": page_url,
                "json": 1,
            }
            if invisible:
                submit_data["invisible"] = 1
            
            async with session.post(f"{self.api_url}/in.php", data=submit_data) as resp:
                result = await resp.json()
                if result.get("status") != 1:
                    return None
                task_id = result.get("request")
            
            # Poll
            for _ in range(120):
                await asyncio.sleep(5)
                async with session.get(
                    f"{self.api_url}/res.php",
                    params={"key": self.api_key, "action": "get", "id": task_id, "json": 1}
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") != "CAPCHA_NOT_READY":
                        return None
        return None
    
    async def _solve_recaptcha_capsolver(
        self,
        page_url: str,
        sitekey: str,
        invisible: bool,
    ) -> Optional[str]:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            task_data = {
                "clientKey": self.api_key,
                "task": {
                    "type": "ReCaptchaV2TaskProxyLess" if not invisible else "ReCaptchaV2EnterpriseTaskProxyLess",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                }
            }
            
            async with session.post(f"{self.api_url}/createTask", json=task_data) as resp:
                result = await resp.json()
                if result.get("errorId") != 0:
                    return None
                task_id = result.get("taskId")
            
            for _ in range(120):
                await asyncio.sleep(5)
                async with session.post(
                    f"{self.api_url}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id}
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == "ready":
                        return result.get("solution", {}).get("gRecaptchaResponse")
                    elif result.get("status") == "failed":
                        return None
        return None
    
    async def _solve_hcaptcha_2captcha(self, page_url: str, sitekey: str) -> Optional[str]:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            submit_data = {
                "key": self.api_key,
                "method": "hcaptcha",
                "sitekey": sitekey,
                "pageurl": page_url,
                "json": 1,
            }
            
            async with session.post(f"{self.api_url}/in.php", data=submit_data) as resp:
                result = await resp.json()
                if result.get("status") != 1:
                    return None
                task_id = result.get("request")
            
            for _ in range(120):
                await asyncio.sleep(5)
                async with session.get(
                    f"{self.api_url}/res.php",
                    params={"key": self.api_key, "action": "get", "id": task_id, "json": 1}
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        return result.get("request")
                    elif result.get("request") != "CAPCHA_NOT_READY":
                        return None
        return None
    
    async def _solve_hcaptcha_capsolver(self, page_url: str, sitekey: str) -> Optional[str]:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            task_data = {
                "clientKey": self.api_key,
                "task": {
                    "type": "HCaptchaTaskProxyLess",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                }
            }
            
            async with session.post(f"{self.api_url}/createTask", json=task_data) as resp:
                result = await resp.json()
                if result.get("errorId") != 0:
                    return None
                task_id = result.get("taskId")
            
            for _ in range(120):
                await asyncio.sleep(5)
                async with session.post(
                    f"{self.api_url}/getTaskResult",
                    json={"clientKey": self.api_key, "taskId": task_id}
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == "ready":
                        return result.get("solution", {}).get("gRecaptchaResponse")
                    elif result.get("status") == "failed":
                        return None
        return None


class CaptchaImageSolver:
    """Solve simple image CAPTCHAs using OCR (Tesseract)."""
    
    def __init__(self, tesseract_path: Optional[str] = None):
        self.tesseract_path = tesseract_path or "tesseract"
    
    async def solve_image_captcha(
        self,
        image_path: str,
        preprocess: bool = True,
    ) -> Optional[str]:
        """Solve CAPTCHA from image file using OCR."""
        try:
            # Preprocess image if needed
            if preprocess:
                image_path = await self._preprocess_image(image_path)
            
            # Run Tesseract OCR
            import subprocess
            result = subprocess.run(
                [self.tesseract_path, image_path, "stdout", "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            
            text = result.stdout.strip().replace(" ", "").replace("\n", "")
            return text if text else None
            
        except Exception:
            return None
    
    async def _preprocess_image(self, image_path: str) -> str:
        """Preprocess image for better OCR results."""
        try:
            from PIL import Image, ImageFilter, ImageEnhance
            import tempfile
            
            img = Image.open(image_path)
            
            # Convert to grayscale
            img = img.convert("L")
            
            # Increase contrast
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.0)
            
            # Increase sharpness
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            
            # Apply threshold
            img = img.point(lambda x: 0 if x < 128 else 255)
            
            # Resize if too small
            if img.width < 100 or img.height < 50:
                img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
            
            # Save processed image
            temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            img.save(temp_file.name)
            return temp_file.name
            
        except Exception:
            return image_path


def apply_stealth(
    context: BrowserContext,
    config: Optional[StealthConfig] = None,
) -> StealthManager:
    manager = StealthManager(config)
    asyncio.create_task(manager.apply_to_context(context))
    return manager