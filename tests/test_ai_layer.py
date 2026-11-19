"""AI layer with mocked providers: no network, no cost, no real keys."""
import io
import json
import logging
import sys
import types

import pytest

from jarvis.ai import briefs, client, copilot, explain, nl_alerts, review, tools
from jarvis.ai.providers import base as ai_base, gemini as gemini_mod
from jarvis.ai.providers.base import ChatResult, Provider, ProviderBusy, ProviderError, ToolCall
from jarvis.ai.providers.claude import ClaudeProvider
from jarvis.ai.providers.gemini import GeminiProvider
from jarvis.markets import api as markets_api
from jarvis.markets.data import store

FAKE_KEY = "TESTKEY-123"
PROV = {"source": "nse:option-chain@test", "kind": "live", "as_of": 1.0, "age_sec": 12.0}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    for v in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "JARVIS_AI_PROVIDER", "JARVIS_AI_MODEL"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "m.db"))
    copilot.MEMORY._d.clear()
    explain._cache.clear()
    gemini_mod._discovery.update(at=0.0, ttl=0.0, models=None)
    ai_base.note_call(None, False, [])


class FakeProvider(Provider):
    """Scripted turns: each item is a ChatResult returned by the next chat() call."""
    name, model = "fake", "fake-1"

    def __init__(self, turns=(), structured_out=None):
        self.turns, self.calls, self.structured_out = list(turns), [], structured_out

    def available(self):
        return True

    def chat(self, messages, tools_, system, effort="medium"):
        self.calls.append({"messages": list(messages), "tools": tools_, "system": system})
        return self.turns.pop(0) if self.turns else ChatResult(text="done")

    def structured(self, prompt, json_schema, system=""):
        self.last_schema = json_schema
        return self.structured_out

    def user(self, t):
        return {"role": "user", "content": t}

    def assistant_text(self, t):
        return {"role": "assistant", "content": t}

    def append_turn(self, m, r):
        m.append({"role": "assistant", "calls": [c.name for c in r.tool_calls]})

    def append_tool_results(self, m, results):
        m.append({"role": "tool", "content": [p for _, p in results]})


@pytest.fixture
def fake_handler(monkeypatch):
    seen = []

    def h(q):
        seen.append(q)
        strikes = [{"strike": 23000.0 + 50 * i, "call": {"oi": i}} for i in range(60)]
        return {"symbol": q["symbol"][0], "spot": 24012.5, "atm_strike": 24000.0, "pcr": {"oi": 1.12}, "strikes": strikes, "prov": PROV}
    monkeypatch.setitem(markets_api._HANDLERS, "/api/markets/fno/analytics", h)
    return seen


# ---------------------------------------------------------------- selection + status

def test_no_key_means_no_provider():
    assert client.get_provider() is None
    assert client.status() == {"provider": None, "model": None, "available": False, "requested": "auto",
                               "busy": False, "last_model_used": None, "fallbacks_tried": []}


def test_gemini_selected_with_its_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    p = client.get_provider()
    assert p.name == "gemini" and p.model == "gemini-3.8-flash"
    monkeypatch.setenv("JARVIS_AI_MODEL", "gemini-x")
    assert client.get_provider().model == "gemini-x"


def test_claude_preferred_when_both_and_override(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", types.ModuleType("anthropic"))
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert client.get_provider().name == "claude"
    assert client.get_provider().model == "claude-opus-5-5"
    monkeypatch.setenv("JARVIS_AI_PROVIDER", "gemini")
    assert client.get_provider().name == "gemini"


def test_claude_without_sdk_is_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import fails
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    assert client.get_provider() is None


def test_status_never_contains_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    s = client.status()
    assert s["available"] and s["provider"] == "gemini"
    assert FAKE_KEY not in json.dumps(s)


# ---------------------------------------------------------------- tools

def test_tool_calls_real_handler_and_trims_strikes(fake_handler):
    out = tools.execute("fno_analytics", {"symbol": "NIFTY"})
    assert fake_handler == [{"symbol": ["NIFTY"]}]
    assert out["prov"] == PROV and len(out["strikes"]) == 21
    assert out["strikes"][10]["strike"] == 24000.0


def test_inst_routes_discovered_dynamically(monkeypatch):
    names = {t["name"] for t in tools.specs()}
    assert "inst_participant_oi" not in names
    monkeypatch.setitem(markets_api._HANDLERS, "/api/markets/inst/participant-oi", lambda q: {"rows": [], "prov": PROV})
    specs = tools.specs()
    assert "inst_participant_oi" in {t["name"] for t in specs}
    assert [t["name"] for t in specs] == sorted(t["name"] for t in specs)  # deterministic for caching
    assert tools.execute("inst_participant_oi", {})["prov"] == PROV


def test_no_order_tool_exists():
    assert not [t for t in tools.specs() if any(w in t["name"] for w in ("order", "place", "close", "trade"))]


# ---------------------------------------------------------------- copilot

def test_copilot_answers_from_tools_with_citations(fake_handler):
    p = FakeProvider([ChatResult(text="", tool_calls=[ToolCall("1", "fno_analytics", {"symbol": "NIFTY"})], stop_reason="tool_use"),
                      ChatResult(text="NIFTY PCR is 1.12 (nse option chain, live, 12 s old).")])
    out = copilot.ask("what is nifty pcr", session_id="s1", provider=p)
    assert "1.12" in out["answer"] and out["tools_used"][0]["name"] == "fno_analytics"
    assert out["citations"][0]["source"] == PROV["source"] and out["citations"][0]["age_sec"] == 12.0
    assert out["followups"]
    assert p.calls[0]["system"] == copilot.SYSTEM_PROMPT
    # memory: second question carries the first turn
    copilot.ask("and banknifty?", session_id="s1", provider=FakeProvider([ChatResult(text="Need data.")]))
    assert len(copilot.MEMORY.get("s1")) == 2


def test_grounding_guard_reasks_then_refuses():
    p = FakeProvider([ChatResult(text="NIFTY will hit 25000."), ChatResult(text="Probably 24800.")])
    out = copilot.ask("where will nifty go", provider=p)
    assert out["answer"] == copilot.REFUSE_TO_GUESS and out["guarded"] and len(p.calls) == 2
    assert "Use the tools" in p.calls[1]["messages"][-1]["content"]


def test_grounding_guard_accepts_tool_backed_retry(fake_handler):
    p = FakeProvider([ChatResult(text="About 1.1."),
                      ChatResult(text="", tool_calls=[ToolCall("1", "fno_analytics", {"symbol": "NIFTY"})], stop_reason="tool_use"),
                      ChatResult(text="PCR 1.12 (live).")])
    out = copilot.ask("nifty pcr", provider=p)
    assert out["answer"] == "PCR 1.12 (live)." and not out["guarded"]


def test_words_only_answer_needs_no_tool():
    out = copilot.ask("can you place an order", provider=FakeProvider([ChatResult(text="I can't place orders; use the order ticket.")]))
    assert "order ticket" in out["answer"] and not out["guarded"]


def test_fallback_without_key():
    out = copilot.ask("nifty pcr")
    assert out["available"] is False and out["answer"] == copilot.NO_PROVIDER


def test_copilot_route_falls_back_to_rule_based(monkeypatch):
    from jarvis.api import server
    assert client.get_provider() is None
    h = _handler(server)
    h.path = "/api/copilot/ask"
    body = json.dumps({"query": "help"}).encode()
    h.headers = {"Content-Length": str(len(body))}
    h.rfile = io.BytesIO(body)
    h.do_POST()
    payload = json.loads(h.wfile.getvalue().decode())
    assert payload["provider"] is False and "ai" not in payload and payload["response"]


# ---------------------------------------------------------------- NL alerts, briefs, explain, review

def test_nl_alert_parsing_validates_rules():
    p = FakeProvider(structured_out={"rules": [{"type": "level_cross", "symbol": "nifty", "level": 24500, "direction": "above"},
                                               {"type": "pcr_cross", "symbol": "NIFTY"}], "unparsed": ""})
    out = nl_alerts.parse("tell me when nifty goes above 24500", provider=p)
    assert out["rules"] == [{"type": "level_cross", "symbol": "NIFTY", "level": 24500.0, "direction": "above", "market": "IN"}]
    assert out["errors"] and out["confirm_required"]
    assert "level_cross" in p.last_schema["properties"]["rules"]["items"]["properties"]["type"]["enum"]
    from jarvis.markets import alerts
    assert alerts.list_rules() == []  # parse never saves


def test_nl_alert_without_provider():
    assert nl_alerts.parse("x")["rules"] == []


FACTS = {"kind": "pre", "generated_at_ist": "2026-11-18 08:50",
         "global_cues": [{"name": "S&P 500", "price": 6000.5, "change_pct": 0.4, "prov": PROV}],
         "indices": {"rows": [{"name": "NIFTY 50", "last": 24012.5, "change_pct": 0.3}], "prov": PROV},
         "vix": {"value": 13.2, "year_low": 10.0, "year_high": 22.0, "prov": PROV},
         "fii_dii": {"rows": [{"category": "FII/FPI", "date": "17-Nov-2026", "net_cr": -1234.0}], "prov": PROV},
         "options_NIFTY": {"spot": 24012.5, "expiry": "27-Nov-2026", "max_pain": 24000.0, "pcr": {"oi": 1.12},
                           "walls": {"resistance": [{"strike": 24500.0}], "support": [{"strike": 23500.0}]},
                           "expected_move": {"one_sd": 310.0}, "prov": PROV},
         "adviser_scan": {"scanned": 8, "opportunities": [], "prov": PROV},
         "ledger": {"closed": 3, "win_rate": 66.7, "avg_pnl_per_lot": 210.0, "open": 1}}


def test_template_brief_copies_only_fact_sheet_figures():
    b = briefs.generate("pre", facts=FACTS, use_provider=False)
    t = b["text"]
    for fig in ("6,000.50", "24,012.50", "13.20", "-1,234", "24,000", "1.12", "310.00", "66.7"):
        assert fig in t, fig
    assert "BANKNIFTY" in t and "unavailable" in t and "no trade / insufficient evidence" in t
    assert briefs.latest("pre")["text"] == t and b["provider"] == "template"


def test_brief_with_provider_and_failure_falls_back():
    p = FakeProvider([ChatResult(text="Headline: calm open.")])
    assert briefs.generate("post", provider=p, facts=FACTS)["text"] == "Headline: calm open."
    assert "Fact sheet" in p.calls[0]["messages"][0]["content"]

    class Boom(FakeProvider):
        def chat(self, *a, **k):
            raise ProviderError("down")
    assert briefs.generate("post", provider=Boom(), facts=FACTS)["provider"] == "template"


def test_explain_definitions_fallback_and_cache():
    a = explain.explain("PCR", "1.35", {"symbol": "nifty"})
    assert a["source"] == "definitions" and "put-heavy" in a["text"] and "1.35" in a["text"]
    assert len(explain.DEFINITIONS) >= 25
    p = FakeProvider([ChatResult(text="Puts dominate. Sentiment leans protective.")])
    assert explain.explain("pcr", "1.36", {"symbol": "NIFTY"}, provider=p)["source"] == "definitions"  # same bucket → cached
    assert explain.explain("gex", "-5", provider=p)["source"] == "fake"
    assert explain.explain("unknown_metric", 1)["source"] == "none"


def test_weekly_review_template(monkeypatch):
    import time as _t
    from jarvis.markets import ledger
    items = [{"ts": _t.time(), "symbol": "NIFTY", "strategy": "bull_call", "status": "CLOSED", "pnl_per_lot": 300.0},
             {"ts": _t.time(), "symbol": "NIFTY", "strategy": "iron_condor", "status": "CLOSED", "pnl_per_lot": -100.0}]
    monkeypatch.setattr(ledger, "summary", lambda: {"items": items, "recorded": 2, "closed": 2, "win_rate": 50.0, "avg_pnl_per_lot": 100.0})
    r = review.weekly_review(use_provider=False)
    assert r["stats"]["closed"] == 2 and r["stats"]["win_rate"] == 50.0 and "too small" in r["text"]


# ---------------------------------------------------------------- provider wire formats (mocked transport)

class FakeResp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body
        self.text = json.dumps(body)

    def json(self):
        return self._b


class FakeSession:
    def __init__(self, responses):
        self.responses, self.sent = list(responses), []

    def post(self, url, json=None, headers=None, timeout=None):
        self.sent.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def test_gemini_wire_format_and_tool_loop(monkeypatch, fake_handler):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    s = FakeSession([
        FakeResp(200, {"id": "i1", "status": "requires_action", "steps": [
            {"type": "thought", "signature": "sig"},
            {"type": "function_call", "id": "c1", "name": "fno_analytics", "arguments": {"symbol": "NIFTY"}}]}),
        FakeResp(200, {"id": "i2", "status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "PCR 1.12 (live, 12 s)."}]}]}),
    ])
    out = copilot.ask("nifty pcr", provider=GeminiProvider(session=s))
    assert out["answer"] == "PCR 1.12 (live, 12 s)."
    first, second = s.sent
    assert first["url"].endswith("/v1beta/interactions") and first["headers"]["x-goog-api-key"] == FAKE_KEY
    assert first["json"]["model"] == "gemini-3.8-flash" and first["json"]["store"] is False
    assert first["json"]["tools"][0]["type"] == "function" and first["json"]["system_instruction"] == copilot.SYSTEM_PROMPT
    steps = second["json"]["input"]
    assert {"type": "thought", "signature": "sig"} in steps  # model steps passed back unchanged
    fr = steps[-1]
    assert fr["type"] == "function_result" and fr["call_id"] == "c1" and json.loads(fr["result"][0]["text"])["prov"] == PROV
    assert FAKE_KEY not in json.dumps([x["json"] for x in s.sent])


class ListingSession(FakeSession):
    """FakeSession that also answers GET /v1beta/models."""

    def __init__(self, responses, models):
        super().__init__(responses)
        self.models, self.gets = models, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers})
        return FakeResp(200, {"models": [{"name": f"models/{m}"} for m in self.models]})


BUSY = FakeResp(503, {"error": {"code": 503, "message": "The model is currently experiencing high demand."}})
OK = FakeResp(200, {"status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "fine"}]}]})
LISTED = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-latest", "gemini-pro-latest"]


def test_gemini_503_retries_then_falls_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    s = ListingSession([BUSY] * 6 + [OK], LISTED)
    slept = []
    p = GeminiProvider(session=s, sleep=slept.append)
    out = copilot.ask("why is gold up", provider=p)
    assert out["answer"] == "fine" and out["model"] == "gemini-3.5-flash" and out["retried"] >= 4
    used = [x["json"]["model"] for x in s.sent]
    # 3 tries each on 3.8 and 3.7; 3.6 is not listed for this key so it is skipped
    assert used == ["gemini-3.8-flash"] * 3 + ["gemini-3.7-flash"] * 3 + ["gemini-3.5-flash"]
    assert slept and all(0 < d <= 8 for d in slept) and sum(slept) <= 2 * gemini_mod.MODEL_BUDGET_S
    st = client.status()
    assert st["busy"] is False and st["last_model_used"] == "gemini-3.5-flash"
    assert st["fallbacks_tried"] == ["gemini-3.8-flash", "gemini-3.7-flash"]


def test_gemini_all_busy_is_reported(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)
    s = ListingSession([BUSY] * 50, LISTED)
    out = copilot.ask("why is gold up", provider=GeminiProvider(session=s, sleep=lambda d: None))
    assert out["busy"] is True and out["answer"] == "AI busy at Google (503) — retried 4 models"
    assert {x["json"]["model"] for x in s.sent} == {"gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-latest"}
    assert len(s.sent) == 12  # 3 tries x 4 listed models, bounded
    assert client.status()["busy"] is True
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in json.dumps(out)


def test_gemini_non_retryable_error_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    s = ListingSession([FakeResp(400, {"error": "bad"})], LISTED)
    with pytest.raises(ProviderError) as e:
        GeminiProvider(session=s, sleep=lambda d: None).chat([], [], "s")
    assert not isinstance(e.value, ProviderBusy) and len(s.sent) == 1


def test_gemini_discovery_is_cached(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    s = ListingSession([OK] * 4, LISTED)
    for _ in range(3):
        GeminiProvider(session=s).chat([], [], "s")
    assert len(s.gets) == 1 and s.gets[0]["url"].endswith("/v1beta/models")
    assert s.gets[0]["headers"]["x-goog-api-key"] == FAKE_KEY
    monkeypatch.setattr(gemini_mod.time, "time", lambda: gemini_mod._discovery["at"] + gemini_mod.DISCOVERY_TTL_S + 1)
    GeminiProvider(session=s).chat([], [], "s")
    assert len(s.gets) == 2  # refreshed after 6 h


def test_gemini_fallback_mid_tool_loop_restarts_turn(monkeypatch, fake_handler):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    call = FakeResp(200, {"status": "requires_action", "steps": [
        {"type": "thought", "signature": "sig-38"},
        {"type": "function_call", "id": "c1", "name": "fno_analytics", "arguments": {"symbol": "NIFTY"}}]})
    call2 = FakeResp(200, {"status": "requires_action", "steps": [
        {"type": "function_call", "id": "c2", "name": "fno_analytics", "arguments": {"symbol": "NIFTY"}}]})
    done = FakeResp(200, {"status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": "PCR 1.12."}]}]})
    s = ListingSession([call, BUSY, BUSY, BUSY, call2, done], LISTED)
    out = copilot.ask("nifty pcr", provider=GeminiProvider(session=s, sleep=lambda d: None))
    assert out["answer"] == "PCR 1.12." and out["model"] == "gemini-3.7-flash"
    restart, final = s.sent[4]["json"], s.sent[5]["json"]
    assert restart["model"] == "gemini-3.7-flash" and [x["type"] for x in restart["input"]] == ["user_input"]
    assert "sig-38" not in json.dumps(final["input"])  # no 3.8 steps sent to 3.7
    assert len(fake_handler) == 2  # the turn's tool ran again on the new model


def test_claude_sdk_retries_configured_and_overload_is_busy(monkeypatch):
    seen = {}
    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda **kw: seen.update(kw) or "client"
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    assert ClaudeProvider().client == "client" and seen == {"max_retries": 4}

    class Overloaded(Exception):
        status_code, message = 529, "Overloaded"

    class Boom(FakeAnthropic):
        def _create(self, **kw):
            raise Overloaded()
    out = copilot.ask("x", provider=ClaudeProvider(client=Boom([])))
    assert out["busy"] and out["answer"].startswith("AI busy at Anthropic (529)")
    assert client.status()["busy"] is True


def test_gemini_structured_output(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    s = FakeSession([FakeResp(200, {"status": "completed", "steps": [
        {"type": "model_output", "content": [{"type": "text", "text": '{"rules": []}'}]}]})])
    assert GeminiProvider(session=s).structured("x", {"type": "object"}) == {"rules": []}
    assert s.sent[0]["json"]["response_format"] == {"type": "text", "mime_type": "application/json", "schema": {"type": "object"}}


def _block(**kw):
    return types.SimpleNamespace(**kw)


class FakeAnthropic:
    def __init__(self, responses):
        self.responses, self.kwargs = list(responses), []
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.kwargs.append(kw)
        return self.responses.pop(0)


def test_claude_request_shape_and_tool_loop(fake_handler):
    fc = FakeAnthropic([
        _block(stop_reason="tool_use", content=[_block(type="thinking", thinking=""),
                                                _block(type="tool_use", id="tu1", name="fno_analytics", input={"symbol": "NIFTY"})]),
        _block(stop_reason="end_turn", content=[_block(type="text", text="PCR 1.12 (live).")]),
    ])
    out = copilot.ask("nifty pcr", provider=ClaudeProvider(client=fc))
    assert out["answer"] == "PCR 1.12 (live)."
    k0, k1 = fc.kwargs
    assert k0["model"] == "claude-opus-5-5" and k0["thinking"] == {"type": "adaptive"}
    assert k0["output_config"] == {"effort": "medium"} and k0["tool_choice"] == {"type": "auto"}
    assert k0["betas"] == ["server-side-fallback-2026-07-01"] and k0["fallbacks"] == "default"
    assert k0["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in k0["tools"]] == sorted(t["name"] for t in k0["tools"])
    assert k1["messages"][-2]["role"] == "assistant" and k1["messages"][-2]["content"][0].type == "thinking"
    assert k1["messages"][-1]["content"][0]["type"] == "tool_result" and k1["messages"][-1]["content"][0]["tool_use_id"] == "tu1"


def test_claude_refusal_and_max_tokens():
    fc = FakeAnthropic([_block(stop_reason="refusal", content=[]),
                        _block(stop_reason="max_tokens", content=[_block(type="tool_use", id="x", name="ledger", input={})])])
    p = ClaudeProvider(client=fc)
    assert p.chat([], [], "s").stop_reason == "refusal"
    r = p.chat([], [], "s")
    assert r.stop_reason == "max_tokens" and r.tool_calls == []  # never run a truncated tool call
    assert copilot.ask("x", provider=ClaudeProvider(client=FakeAnthropic([_block(stop_reason="refusal", content=[])])))["answer"].startswith("The model declined")


# ---------------------------------------------------------------- the key never leaks

def test_key_never_in_logs_responses_or_files(monkeypatch, caplog, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    caplog.set_level(logging.DEBUG)
    leaky = FakeSession([FakeResp(401, {"error": f"API key {FAKE_KEY} not valid"})] * 4)
    p = GeminiProvider(session=leaky)
    out = copilot.ask("nifty pcr", provider=p)
    with pytest.raises(ProviderError) as e:
        p.structured("x", {"type": "object"})
    b = briefs.generate("pre", provider=GeminiProvider(session=FakeSession([FakeResp(500, {"error": FAKE_KEY})] * 18),
                                                        sleep=lambda d: None), facts=FACTS)
    from jarvis.api import server
    h = _handler(server)
    h._ai_get("/api/ai/status", {})
    blobs = [json.dumps(out), str(e.value), json.dumps(b, default=str), caplog.text, h.wfile.getvalue().decode()]
    blobs += [f.read_bytes().decode("latin-1") for f in tmp_path.rglob("*") if f.is_file()]
    assert all(FAKE_KEY not in x for x in blobs)
    assert "[REDACTED]" in str(e.value)


def _handler(server):
    class H(server.JarvisRequestHandler):
        def __init__(self):
            self.headers = {}
            self.wfile = io.BytesIO()
            self.client_address = ("127.0.0.1", 1)
            self.codes = []

        def send_response(self, code, message=None):
            self.codes.append(code)

        def send_header(self, *a):
            pass

        def end_headers(self):
            pass

        def _get_auth_user(self):
            return {"username": "test", "role": "ADMIN"}

        def send_error(self, code, message=None, explain=None):
            self.codes.append(code)
    return H()


# ---------------------------------------------------------------- forex: generated bars never leave the API

def test_candles_route_refuses_fallback_frames(monkeypatch):
    import pandas as pd
    from jarvis.api import server
    df = pd.DataFrame({"time": pd.to_datetime([1_700_000_000], unit="s"), "open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [0]})
    df.attrs["data_source"] = "SYNTHETIC_FALLBACK"
    feed = types.SimpleNamespace(fetch_rates=lambda *a, **k: df)
    monkeypatch.setattr(server.JarvisRequestHandler, "data_feed", feed)
    server.JarvisRequestHandler._CANDLES_CACHE.clear()
    for path in ("/api/candles?symbol=ZZZUSD&tf=H1", "/api/rates?symbol=ZZZUSD&tf=H1"):
        h = _handler(server)
        h.path = path
        h.do_GET()
        body = json.loads(h.wfile.getvalue().decode())
        assert body.get("candles", body.get("rates")) == [] and body["prov"]["kind"] == "unavailable"
    df.attrs["data_source"] = "LIVE_MT5"
    server.JarvisRequestHandler._CANDLES_CACHE.clear()
    h = _handler(server)
    h.path = "/api/candles?symbol=ZZZUSD&tf=H1"
    h.do_GET()
    body = json.loads(h.wfile.getvalue().decode())
    assert len(body["candles"]) == 1 and body["prov"]["kind"] == "live"
