"""Regression: composition wires the live persona catalog (Item 2, hot-reload)."""

from __future__ import annotations

from pathlib import Path

import pytest

import diana
from diana.composition import AppContainer


@pytest.fixture
def _comp_src() -> str:
    root = Path(diana.__file__).resolve().parent
    return (root / "composition.py").read_text(encoding="utf-8")


def test_composition_persona_admin_wired(_comp_src: str) -> None:
    """Item 2: PersonaAdminService + provider + invalidation are wired in build_app."""
    assert "from diana.application.persona_admin_service import PersonaAdminService" in _comp_src
    assert "from diana.application.persona_catalog_provider import PersonaCatalogProvider" in _comp_src
    assert "from diana.infrastructure.db.repositories.persona_versions import PersonaVersionRepo" in _comp_src
    assert "persona_version_repo = PersonaVersionRepo(sf)" in _comp_src
    assert "PersonaAdminService(" in _comp_src
    assert "PersonaCatalogProvider(" in _comp_src
    assert "set_on_change(persona_catalog_provider.invalidate)" in _comp_src


def test_composition_provider_passed_to_registry_and_director(_comp_src: str) -> None:
    """The SAME provider object reaches both registry retrievers and the Director."""
    count = _comp_src.count("persona_catalog_provider=persona_catalog_provider")
    assert count >= 2  # build_default_registry(...) + CognitiveDirector(...)


def test_composition_wiring_block_before_registry(_comp_src: str) -> None:
    """The live-catalog wiring block must come before build_default_registry."""
    provider_idx = _comp_src.index("PersonaCatalogProvider(")
    registry_idx = _comp_src.index("build_default_registry(")
    assert provider_idx < registry_idx


def test_app_container_has_persona_admin_field() -> None:
    assert "persona_admin" in AppContainer.__dataclass_fields__
    field = AppContainer.__dataclass_fields__["persona_admin"]
    assert field.default is None


def test_composition_passes_persona_admin_to_dispatcher(_comp_src: str) -> None:
    """Item 3: build_dispatcher receives the persona admin service + flag."""
    assert "persona_admin=persona_admin_service" in _comp_src
    assert "feature_persona_admin_enabled=settings.feature_persona_admin_enabled" in _comp_src


def test_menu_router_receives_persona_admin_and_flag() -> None:
    """build_menu_router signature accepts persona_admin + feature flag."""
    import inspect

    from diana.telegram.handlers.menu import build_menu_router

    params = inspect.signature(build_menu_router).parameters
    assert "persona_admin" in params
    assert "feature_persona_admin_enabled" in params
    assert params["feature_persona_admin_enabled"].default is False


def test_dispatcher_accepts_persona_admin_kwargs() -> None:
    import inspect

    from diana.telegram.setup import build_dispatcher

    params = inspect.signature(build_dispatcher).parameters
    assert "persona_admin" in params
    assert "feature_persona_admin_enabled" in params


def test_menu_router_flag_gate_shadows_persona_admin() -> None:
    """With the feature off, the panel is inert (persona_admin forced to None)."""
    from pathlib import Path

    import diana

    root = Path(diana.__file__).resolve().parent
    src = (root / "telegram" / "handlers" / "menu.py").read_text(encoding="utf-8")
    assert "persona_admin = persona_admin if feature_persona_admin_enabled else None" in src
