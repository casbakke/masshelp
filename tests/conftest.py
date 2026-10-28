from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from masshelp.agent.llm import ScriptedLLM  # noqa: E402
from masshelp.config import Settings, get_settings  # noqa: E402
from masshelp.messaging import FakeMessenger  # noqa: E402
from masshelp.rules.models import load_rules  # noqa: E402
from masshelp.services import build_services  # noqa: E402

MARIA = "+16175550101"
CARLOS = "+16175550102"
UNKNOWN = "+16175559999"


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    s = Settings(_env_file=None, data_dir=tmp_path, twilio_validate=False, demo_today=date(2026, 12, 1),
                 public_base_url="https://masshelp.test", anthropic_api_key=None)
    # util.dates.today() reads get_settings(); point it at the test settings.
    monkeypatch.setattr("masshelp.util.dates.get_settings", lambda: s)
    get_settings.cache_clear()
    return s


@pytest.fixture
def rules(settings):
    return load_rules(settings.rules_path)


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM()


@pytest.fixture
def messenger() -> FakeMessenger:
    return FakeMessenger()


@pytest.fixture
def services(settings, llm, messenger):
    return build_services(settings, llm=llm, messenger=messenger)
