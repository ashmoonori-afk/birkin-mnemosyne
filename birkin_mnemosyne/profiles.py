"""Automatic role-profile memory with background review."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .mnemosyne import atomic_write

PROFILE_DESCRIPTIONS = {
    "user": "User characteristics and stable personal context.",
    "preferences": "User preferences and favored choices.",
    "soul": "Conversation style and interaction guidance.",
    "workflow": "User work process and execution guidance.",
    "automation": "User workflow automation guidance.",
}

_PROFILE_TITLES = {
    "user": "User",
    "preferences": "Preferences",
    "soul": "Soul",
    "workflow": "Workflow",
    "automation": "Automation",
}
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _vault_lock(vault: Path) -> threading.Lock:
    key = vault.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


@dataclass(frozen=True)
class ProfileExchange:
    """One conversation exchange submitted for durable profile review."""

    user: str
    assistant: str


class ProfileReviewError(ValueError):
    """The reviewer returned data outside the role-profile contract."""


ProfileReviewer = Callable[[ProfileExchange], str]


class ProfileMemory:
    """Persist reviewed profile guidance without blocking the conversation."""

    def __init__(self, vault: Path, review: ProfileReviewer):
        self._vault = Path(vault)
        self._system = self._vault / "system"
        self._review = review
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="mnemosyne-profile-review",
        )
        self._state_lock = threading.Lock()
        self._pending: list[Future[None]] = []
        self._closed = False
        self._bootstrap()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def record_exchange(
        self,
        user: str,
        assistant: str,
    ) -> Future[None]:
        """Queue an exchange for review and return without waiting for it."""
        exchange = ProfileExchange(user=user, assistant=assistant)
        with self._state_lock:
            if self._closed:
                raise RuntimeError("profile memory is closed")
            future = self._executor.submit(self._review_and_save, exchange)
            self._pending.append(future)
            return future

    def flush(self) -> None:
        """Wait for queued reviews and surface any reviewer failure."""
        with self._state_lock:
            pending, self._pending = self._pending, []
        for future in pending:
            future.result()

    def close(self) -> None:
        """Stop accepting exchanges and release the background worker."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.flush()
        finally:
            self._executor.shutdown()

    def read_profiles(self) -> dict[str, list[str]]:
        """Return persisted guidance for each role profile."""
        return {
            name: self._read_guidance(self._profile_path(name))
            for name in PROFILE_DESCRIPTIONS
        }

    def _bootstrap(self) -> None:
        with _vault_lock(self._vault):
            self._system.mkdir(parents=True, exist_ok=True)
            for name, description in PROFILE_DESCRIPTIONS.items():
                path = self._profile_path(name)
                if path.exists():
                    continue
                text = (
                    "---\n"
                    f"description: {description}\n"
                    "---\n"
                    f"# {_PROFILE_TITLES[name]}\n\n"
                    "## Guidance\n"
                )
                atomic_write(path, text)

    def _profile_path(self, name: str) -> Path:
        return self._system / f"{name}.md"

    def _review_and_save(self, exchange: ProfileExchange) -> None:
        profiles = self._parse_review(self._review(exchange))
        with _vault_lock(self._vault):
            for name, guidance in profiles.items():
                path = self._profile_path(name)
                current = path.read_text(encoding="utf-8")
                line = f"- {guidance}"
                if line in current.splitlines():
                    continue
                atomic_write(path, f"{current.rstrip()}\n{line}\n")

    @staticmethod
    def _parse_review(raw: str) -> dict[str, str]:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProfileReviewError("review must be valid JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"profiles"}:
            raise ProfileReviewError("review must contain only 'profiles'")
        profiles = payload["profiles"]
        if not isinstance(profiles, dict):
            raise ProfileReviewError("'profiles' must be an object")
        unknown = set(profiles) - PROFILE_DESCRIPTIONS.keys()
        if unknown:
            raise ProfileReviewError(f"unknown profile: {min(unknown)}")
        parsed: dict[str, str] = {}
        for name, guidance in profiles.items():
            if not isinstance(guidance, str) or not guidance.strip():
                raise ProfileReviewError(
                    f"profile '{name}' guidance must be a non-empty string"
                )
            parsed[name] = " ".join(guidance.split())
        return parsed

    @staticmethod
    def _read_guidance(path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        _, _, guidance = text.partition("## Guidance")
        return [
            line.removeprefix("- ").strip()
            for line in guidance.splitlines()
            if line.startswith("- ")
        ]
