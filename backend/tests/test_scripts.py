"""The dev scripts in backend/scripts: the demo flow runs end to end against the app."""

import importlib.util
from pathlib import Path
from types import ModuleType

import httpx

from nodly.config import BACKEND_DIR
from tests.fake_supabase import FakeSupabase


def load_script(name: str) -> ModuleType:
    path = Path(BACKEND_DIR, "scripts", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_demo_flow_runs_end_to_end(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    demo = load_script("demo_flow")
    lines: list[str] = []
    result = await demo.run_flow(
        client,
        fake_supabase.token(email="priya@example.com"),
        name="Priya",
        timezone="Asia/Kolkata",
        country="IN",
        say=lines.append,
    )
    assert result["device_me"]["elder"]["id"] == result["elder"]["id"]
    assert result["device_me"]["family"]["id"] == result["family"]["id"]
    assert [line[:2] for line in lines if line[0].isdigit()] == ["1.", "2.", "3.", "4.", "5.", "6."]


async def test_demo_flow_never_guesses_a_timezone(
    client: httpx.AsyncClient, fake_supabase: FakeSupabase
) -> None:
    demo = load_script("demo_flow")
    token = fake_supabase.token(email="newbie@example.com")
    try:
        await demo.run_flow(client, token, country="IN", say=lambda _: None)
    except demo.FlowError as exc:
        assert "--timezone" in str(exc)
    else:
        raise AssertionError("expected FlowError")
