"""SandboxService: fake profile and trace isolation tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from diana.application.sandbox import SandboxService


class FakeProfilesRepo:
    """Minimal profiles repo for testing SandboxService."""

    def __init__(self) -> None:
        self.profiles: list[dict] = []

    async def insert_sandbox(
        self,
        channel_id: str,
        display_name: str,
    ) -> object:
        row = {
            "id": uuid4(),
            "channel_id": channel_id,
            "display_name": display_name,
        }
        self.profiles.append(row)
        return type("_Profile", (), dict(row))()


class FakeTracesRepo:
    """Minimal traces repo for testing SandboxService."""

    def __init__(self) -> None:
        self.metadata: dict[UUID, dict] = {}

    async def set_metadata(self, turn_id: UUID, metadata: dict) -> None:
        self.metadata[turn_id] = metadata


class TestSandboxService:
    """SandboxService constructor and method behavior."""

    async def test_create_without_repos_returns_defaults(self) -> None:
        svc = SandboxService()
        assert svc is not None

    async def test_create_profile_returns_none_when_no_repo(self) -> None:
        svc = SandboxService()
        result = await svc.create_profile(channel_id="ch1", display_name="test")
        assert result is None

    async def test_create_profile_with_repo(self) -> None:
        repo = FakeProfilesRepo()
        svc = SandboxService(profiles_repo=repo)
        result = await svc.create_profile(channel_id="ch1", display_name="Test VIP")
        assert result is not None
        assert hasattr(result, "id")
        assert len(repo.profiles) == 1

    async def test_isolate_trace_returns_false_when_no_repo(self) -> None:
        svc = SandboxService()
        result = await svc.isolate_trace(uuid4())
        assert result is False

    async def test_isolate_trace_with_repo(self) -> None:
        repo = FakeTracesRepo()
        svc = SandboxService(traces_repo=repo)
        turn_id = uuid4()
        result = await svc.isolate_trace(turn_id)
        assert result is True
        assert turn_id in repo.metadata
        assert repo.metadata[turn_id] == {"sandbox": True}
