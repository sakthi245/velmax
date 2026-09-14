"""Module reload utility for development and testing."""

import importlib
import sys
import shutil
from pathlib import Path
from contextlib import contextmanager
from typing import List, Optional, Set


class ModuleReloader:
    """Utility for reloading modules during development and testing."""
    
    def __init__(self, package_prefixes: Optional[List[str]] = None):
        self.package_prefixes = package_prefixes or ['scraper', 'scripts']
        self._original_modules: dict = {}
    
    def save_state(self) -> None:
        """Save current module state for restoration."""
        self._original_modules = {
            name: mod for name, mod in sys.modules.items()
            if any(name.startswith(prefix) for prefix in self.package_prefixes)
        }
    
    def restore_state(self) -> None:
        """Restore original module state."""
        # Remove any modules added after save
        to_remove = [
            name for name in sys.modules
            if any(name.startswith(prefix) for prefix in self.package_prefixes)
            and name not in self._original_modules
        ]
        for name in to_remove:
            del sys.modules[name]
        
        # Restore original modules
        for name, mod in self._original_modules.items():
            sys.modules[name] = mod
    
    def reload_packages(self, packages: Optional[List[str]] = None) -> None:
        """Reload specified packages and their submodules."""
        targets = packages or self.package_prefixes
        
        for prefix in targets:
            # Find all modules matching prefix
            to_reload = [
                name for name in sys.modules
                if name == prefix or name.startswith(prefix + '.')
            ]
            
            # Sort so parent packages reload before children
            to_reload.sort(key=lambda x: x.count('.'))
            
            for name in to_reload:
                try:
                    importlib.reload(sys.modules[name])
                except Exception as e:
                    print(f"Warning: Failed to reload {name}: {e}")
    
    def clear_cache_dirs(self, root: Optional[Path] = None) -> None:
        """Remove all __pycache__ directories."""
        root = root or Path.cwd()
        for cache_dir in root.rglob('__pycache__'):
            try:
                shutil.rmtree(cache_dir)
            except Exception:
                pass  # Ignore permission errors
            
            # Also remove .pyc files
            for pyc_file in root.rglob('*.pyc'):
                try:
                    pyc_file.unlink()
                except Exception:
                    pass


@contextmanager
def reload_context(package_prefixes: Optional[List[str]] = None, 
                   clear_cache: bool = True):
    """Context manager for temporary module reloading."""
    reloader = ModuleReloader(package_prefixes)
    
    try:
        reloader.save_state()
        if clear_cache:
            reloader.clear_cache_dirs()
        yield reloader
    finally:
        reloader.restore_state()


def reload_scraper_modules(clear_cache: bool = True) -> None:
    """Convenience function to reload all scraper modules."""
    reloader = ModuleReloader(['scraper', 'scripts'])
    if clear_cache:
        reloader.clear_cache_dirs()
    reloader.reload_packages(['scraper', 'scripts'])


def auto_reload_on_import() -> None:
    """Decorator to auto-reload modules on import (for development)."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            reload_scraper_modules()
            return func(*args, **kwargs)
        return wrapper
    return decorator