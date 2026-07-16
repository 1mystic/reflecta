"""Reflection text-signal extraction (feature C) - focus on the graceful-degradation
contract, which is what makes it safe to ship without an ANTHROPIC_API_KEY in prod. The
happy path makes a real Claude call and is exercised manually / when a key is present; here
we pin the behaviors that must hold with NO key and on bad input, deterministically."""
from reflecta.reflection import text_signals
from reflecta.reflection.text_signals import ReflectionSignals, extract_reflection_signals


def test_empty_text_returns_none_without_touching_the_api():
    assert extract_reflection_signals("") is None
    assert extract_reflection_signals("   ") is None
    assert extract_reflection_signals(None) is None


def test_no_api_key_degrades_to_none(monkeypatch):
    # force the "no key" world regardless of the local .env, and ensure we never even
    # attempt an import/call - the function must short-circuit on is_available().
    monkeypatch.setattr(text_signals.generation, "is_available", lambda: False)
    assert extract_reflection_signals("I was confident on the joins, guessed on the rest") is None


def test_parses_a_mocked_model_response(monkeypatch):
    """When a key IS available, a valid structured response is returned as-is. We mock the
    Anthropic client so the test is hermetic (no network, no key needed)."""
    monkeypatch.setattr(text_signals.generation, "is_available", lambda: True)

    class _Resp:
        stop_reason = "end_turn"
        parsed_output = ReflectionSignals(
            confidence=0.8, hedging=False,
            misconception_flags=["confuses correlation with causation"],
            summary="You sound sure of your reasoning.")

    class _Msgs:
        def parse(self, **_kwargs):
            return _Resp()

    class _FakeClient:
        messages = _Msgs()

    import sys
    import types
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: _FakeClient()
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    sig = extract_reflection_signals("I understood why correlation isn't causation here")
    assert sig is not None
    assert sig.confidence == 0.8 and sig.hedging is False
    assert sig.misconception_flags == ["confuses correlation with causation"]


def test_refusal_returns_none(monkeypatch):
    monkeypatch.setattr(text_signals.generation, "is_available", lambda: True)

    class _Resp:
        stop_reason = "refusal"
        parsed_output = None

    class _FakeClient:
        class messages:
            @staticmethod
            def parse(**_kwargs):
                return _Resp()

    import sys
    import types
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda *a, **k: _FakeClient()
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    assert extract_reflection_signals("some reflection") is None
