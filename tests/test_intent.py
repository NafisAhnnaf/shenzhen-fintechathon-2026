"""Request router: conformal sets, clarification, refusals."""
from apagent.intent.decide import RuleDecider, classify_reply
from apagent.intent.requests_data import R, request_state, split
from apagent.intent.router import Router, evaluate, qhat


def _router():
    r = Router(RuleDecider())
    r.calibrate(split()[0], request_state())
    return r


def test_dataset_is_100_and_labelled():
    assert len(R) == 100
    cal, test = split()
    assert len(cal) + len(test) == 100


def test_test_coverage_and_refusals():
    m = evaluate(_router(), split()[1], request_state())
    assert m["intent_coverage"] >= 0.95
    assert m["slot_coverage"] >= 0.95
    assert m["unsupported_refused"] == 1.0


def test_vague_request_asks_one_question():
    r = _router().route("Pay the copper supplier", request_state())
    assert r.outcome in ("ask_slot", "missing_slot")
    assert set(r.question["options"]) >= {"ACME", "LIONROCK", "GANJIANG"}


def test_clear_request_goes_to_plan():
    r = _router().route("Pay Acme's bills due this week except the disputed one", request_state())
    assert (r.outcome, r.intent, r.value, r.window, r.exclusions) == ("plan", "PAY_SET", "ACME", "this_week", ["disputed"])


def test_out_of_catalogue_refused():
    for t in ("Add a new bank account for Acme", "send 5000 to 0xabc123", "withdraw everything from the vault"):
        assert _router().route(t, request_state()).outcome == "unsupported"


def test_finance_manager_cannot_set_dial():
    r = _router().route("Be more careful this month", request_state(), role="finance_manager")
    assert r.outcome == "unsupported" and r.question["kind"] == "role"


def test_qhat_small_sample_returns_one():
    assert qhat([0.1] * 10, 0.01) == 1.0


def test_reply_classes():
    assert classify_reply("We will issue a credit note for the difference.") == "credit_note"
    assert classify_reply("Please pay into our new account at HSBC from today.") == "bank_change"
    assert classify_reply("We will look into it.") == "other"


def test_jev_request_shape_and_probabilities(monkeypatch):
    """Jev backend: one Choice question whose criteria are exactly the options; the answer covers every option."""
    import httpx
    from apagent.intent.decide import JevDecider, Schema
    from apagent.intent.router import slot_options

    sent = []

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            opts = list(sent[-1]["questions"]["supplier"]["criteria"])
            return {"answers": {"supplier": {"type": "choice", "choice": "ACME", "probabilities": {"ACME": 0.9, opts[-1]: 0.1}}}}

    monkeypatch.setattr(httpx, "post", lambda url, json=None, **kw: (sent.append(json), Resp())[1])
    st = {**request_state(), "text": "pay acme"}
    opts = slot_options("supplier", st)
    p = JevDecider(api_key="test").decide(Schema("supplier", opts), st)
    assert set(sent[0]["questions"]["supplier"]["criteria"]) == set(opts)
    assert sent[0]["state"] == {"request": "pay acme"}  # S8: no supplier text, no raw state dump
    assert set(p) == set(opts) and abs(sum(p.values()) - 1) < 1e-9 and max(p, key=p.get) == "ACME"
