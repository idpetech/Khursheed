"""
Dependency Injection Container for Enaam

Provides a centralized container for managing service dependencies
and eliminating global state throughout the application.
"""

import threading
from collections.abc import Callable
from typing import Any, Dict, Optional, Type, TypeVar


T = TypeVar('T')


class ServiceContainer:
    """
    Dependency injection container for managing service instances.
    
    Features:
    - Type-safe service registration and retrieval
    - Lazy loading for expensive services
    - Thread-safe singleton instances
    - Factory function support
    """
    
    def __init__(self) -> None:
        self._services: Dict[Type, Any] = {}
        self._factories: Dict[Type, Callable[[], Any]] = {}
        self._lock = threading.RLock()
    
    def register(self, service_type: Type[T], factory: Callable[[], T]) -> None:
        """
        Register a service factory function.
        
        Args:
            service_type: The type/interface to register
            factory: Factory function that creates the service instance
        """
        with self._lock:
            self._factories[service_type] = factory
    
    def register_instance(self, service_type: Type[T], instance: T) -> None:
        """
        Register a pre-created service instance.
        
        Args:
            service_type: The type/interface to register
            instance: The service instance
        """
        with self._lock:
            self._services[service_type] = instance
    
    def get(self, service_type: Type[T]) -> T:
        """
        Get a service instance, creating it if necessary.
        
        Args:
            service_type: The type/interface to retrieve
            
        Returns:
            Service instance of the requested type
            
        Raises:
            ValueError: If service type is not registered
        """
        with self._lock:
            # Return existing instance if available
            if service_type in self._services:
                return self._services[service_type]
            
            # Create new instance using factory
            if service_type not in self._factories:
                raise ValueError(f"Service type {service_type} is not registered")
            
            instance = self._factories[service_type]()
            self._services[service_type] = instance
            return instance
    
    def get_optional(self, service_type: Type[T]) -> Optional[T]:
        """
        Get a service instance if registered, otherwise return None.
        
        Args:
            service_type: The type/interface to retrieve
            
        Returns:
            Service instance or None if not registered
        """
        try:
            return self.get(service_type)
        except (ValueError, Exception):
            # Return None for any service resolution failure
            return None
    
    def is_registered(self, service_type: Type[T]) -> bool:
        """
        Check if a service type is registered.
        
        Args:
            service_type: The type/interface to check
            
        Returns:
            True if registered, False otherwise
        """
        with self._lock:
            return service_type in self._factories or service_type in self._services
    
    def clear(self) -> None:
        """Clear all registered services and factories."""
        with self._lock:
            self._services.clear()
            self._factories.clear()
    
    def create_child_container(self) -> 'ServiceContainer':
        """
        Create a child container that inherits from this one.
        
        Returns:
            New ServiceContainer with inherited registrations
        """
        child = ServiceContainer()
        with self._lock:
            child._factories.update(self._factories)
        return child


# Global container instance for application-wide dependency injection
_default_container: Optional[ServiceContainer] = None
_container_lock = threading.RLock()


def get_default_container() -> ServiceContainer:
    """
    Get the default application-wide service container.
    
    Returns:
        Default ServiceContainer instance
    """
    global _default_container
    
    if _default_container is None:
        with _container_lock:
            if _default_container is None:
                _default_container = ServiceContainer()
                _setup_default_services(_default_container)
    
    return _default_container


def set_default_container(container: ServiceContainer) -> None:
    """
    Set the default application-wide service container.
    
    Args:
        container: ServiceContainer to use as default
    """
    global _default_container
    with _container_lock:
        _default_container = container


def _setup_default_services(container: ServiceContainer) -> None:
    """
    Setup default service registrations.
    
    Args:
        container: ServiceContainer to configure
    """
    from .logging import EnaamLogger
    from .logging import create_logger
    
    # Register logger factory
    container.register(EnaamLogger, lambda: create_logger())


# Convenience functions for default container
def register(service_type: Type[T], factory: Callable[[], T]) -> None:
    """Register a service in the default container."""
    get_default_container().register(service_type, factory)


def register_instance(service_type: Type[T], instance: T) -> None:
    """Register a service instance in the default container."""
    get_default_container().register_instance(service_type, instance)


def resolve(service_type: Type[T]) -> T:
    """Resolve a service from the default container."""
    return get_default_container().get(service_type)


def resolve_optional(service_type: Type[T]) -> Optional[T]:
    """Resolve a service from the default container, returning None if not found."""
    return get_default_container().get_optional(service_type)