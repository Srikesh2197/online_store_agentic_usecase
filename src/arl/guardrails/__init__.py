"""Guardrails for the agent loop (Stage 5), each switchable so arms can be compared.

    prompt.py        the prompt-only defence section
    limits.py        token, dollar and wall-clock budgets (the step cap stays in the loop)
    loopdetect.py    repeated identical calls
    validation.py    grounding of write arguments, length caps
    permissions.py   tiers and taint
    retry.py         retries with backoff for tool faults

The invariants are not here: they are inside the write tools (env/invariants.py), switched
by the trial's environment, because they must hold for every caller.
"""

from dataclasses import dataclass

from arl.guardrails.limits import Budget


@dataclass(frozen=True)
class Guards:
    name: str = "guarded_off"
    prompt: bool = False              # the defence section in the instructions
    limits: Budget | None = None      # token, dollar and time budgets
    loop_detect: bool = False
    validation: bool = False          # grounding and length caps
    retries: bool = False             # retry tool faults; honest message when they run out
    idempotency: bool = False         # a key on every write and escalate call
    taint: bool = False               # block writes after untrusted content
    truncation_retry: bool = False    # one retry of a truncated response, with 2x tokens
    invariants: bool = False          # applied by the runner through conn.env


OFF = Guards()
PROMPT = Guards(name="guarded_prompt", prompt=True)
ALL = Guards(name="guarded_all", prompt=True, limits=Budget(), loop_detect=True,
             validation=True, retries=True, idempotency=True, taint=True,
             truncation_retry=True, invariants=True)
PROFILES = {g.name: g for g in (OFF, PROMPT, ALL)}
