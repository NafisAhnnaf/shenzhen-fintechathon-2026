"""Calibrate the request router on the model (conformal thresholds for intent and slot sets).

    python -m apagent.intent.calibrate_llm      # about 100 model calls on the 53 calibration requests, paced

Writes data/intent_qhat_llm.json; until it exists the model router uses the rule decider's thresholds. The model is
called directly here (no fallback to the rules), so the thresholds describe the model alone.
"""
import json

from . import decide as D
from .router import Router, request_state, split


def main() -> None:
    d = D.default_decider()
    if not isinstance(d, D.FallbackDecider):
        raise SystemExit("no model configured (set GEMINI_API_KEY or LLM_API_KEY)")
    r = Router(d.primary)
    out = r.calibrate(split()[0], request_state())
    r.save()
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
