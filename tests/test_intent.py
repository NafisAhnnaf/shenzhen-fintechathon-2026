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
