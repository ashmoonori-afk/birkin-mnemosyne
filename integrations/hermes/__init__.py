"""Standalone Hermes memory provider; loaded only in a Hermes installation."""

from typing import Protocol

from agent.memory_provider import MemoryProvider

from .provider import VaultProvider


class MnemosyneProvider(VaultProvider, MemoryProvider):
    """Bind the local vault operations to Hermes' public lifecycle contract."""


class RegistrationContext(Protocol):
    def register_memory_provider(self, provider: MemoryProvider) -> None: ...


def register(ctx: RegistrationContext) -> None:
    ctx.register_memory_provider(MnemosyneProvider())
