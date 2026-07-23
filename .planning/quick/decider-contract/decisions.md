# decider-contract — Locked decisions

Source: orchestrator F1-safe locks + impact-analyzer `decider-contract.md` + Anexo F.

| ID | Decision | Status |
|----|----------|--------|
| L1 | `Decision.action` remains `approve \| escalate` only — NEVER expand | LOCKED |
| L2 | Keep safety-threshold escalate + `risk=="alto"` escalate (F1 extension) | LOCKED |
| L3 | F.3 #2 naturalness→regenerate = residual / out of F1 (fall-through approve) | LOCKED residual |
| L4 | Optional audit field `mode_restriction_applied` on supervised approve path; raw send never exposed | LOCKED in-scope |
| L5 | Decider never reads draft text — only EvaluationProfile + Comprehension.risk (+ mode for audit) | LOCKED |
| L6 | Thresholds from ctor dict; composition `eval_thresholds` wire deferred | LOCKED defer |
| L7 | No LLM; pure deterministic | LOCKED |
| L8 | No dirty tree / Behavior / Generator rework | LOCKED |

## Token constants

| Token | Meaning |
|-------|---------|
| `safety_below_threshold` | F.3 #1 escalate reason |
| `risk_high` | F1 risk extension escalate reason |
| `ok_for_human_review` | supervised approve reason |
| `supervised_send_to_approve` | F.2 mode restriction audit value |

## Residual ticket

F.3 rule 2 naturalness→regenerate deferred; F1 fall-through = approve.  
Composition threshold wiring deferred (L6).
