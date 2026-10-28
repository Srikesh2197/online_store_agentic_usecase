"""Retries with backoff for tool backends, and the message when they run out.

Only transient faults are retried (env.faults.ToolFault: a timeout or a 503). An error
*result* (unknown order, policy violation) is an answer, not a fault, and goes back to the
model. Model API errors are not retried here: both provider SDKs already retry connection
errors, 408, 409, 429 and 5xx twice with backoff, so another layer would multiply attempts.

A retried write is only safe with an idempotency key. The loop passes the same key on every
attempt (run id + the model's tool-call id), so an attempt after a lost reply returns the
first result instead of writing again.
"""

import time
from collections.abc import Callable

from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from arl.env.faults import ToolFault

ATTEMPTS = 3


def with_retries(fn: Callable[[], dict], *, attempts: int = ATTEMPTS,
                 sleep: Callable[[float], None] = time.sleep,
                 on_retry: Callable[[int, BaseException], None] = lambda n, exc: None) -> dict:
    """Call fn until it returns, retrying ToolFaults. The last fault is re-raised."""
    retrying = Retrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(multiplier=0.2, max=2.0, jitter=0.2),
        retry=retry_if_exception_type(ToolFault),
        reraise=True,
        sleep=sleep,
        before_sleep=lambda state: on_retry(state.attempt_number, state.outcome.exception()),
    )
    return retrying(fn)


def gave_up(name: str, kind: str, exc: BaseException, attempts: int = ATTEMPTS) -> dict:
    """The honest result after the retries ran out. For a write the outcome is unknown."""
    if kind == "read":
        return {"error": "tool_unavailable",
                "message": f"{name} did not answer after {attempts} attempts "
                           f"({type(exc).__name__}). Tell the customer what you could not "
                           "check; do not guess it."}
    return {"error": "outcome_unknown",
            "message": f"{name} did not answer after {attempts} attempts "
                       f"({type(exc).__name__}). The action may or may not have happened. "
                       "Check with get_order before trying again, or escalate. Do not tell "
                       "the customer it is done unless a lookup confirms it."}
