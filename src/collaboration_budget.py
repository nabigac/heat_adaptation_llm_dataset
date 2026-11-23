"""Account for C requests, estimated capacity, tools, and one final reserve.

Reservations are synchronous: a whole parallel batch is checked before any
await can let another task spend its capacity. API-reported usage is separate
from the deliberately loose UTF-8 request estimate used for admission.
"""

import time


class CollaborationBudgetExceeded(ValueError):
    """Stop investigation without spending the coordinator's final reserve."""


class CollaborationBudget:
    def __init__(self, limits: dict, profiles: dict, *, clock=time.monotonic):
        self.limits = dict(limits)
        self.clock = clock
        self.started = clock()
        self.final_seconds = limits.get("final_generation_seconds", profiles["coordinator"]["model_timeout_seconds"])
        self.reservations = {"coordinator_final": profiles["coordinator"]["context_limit"]}
        self.used_requests = 0
        self.estimated_tokens = 0
        self.tool_counts = dict.fromkeys(profiles, 0)
        self.tool_limits = {actor: profile["max_tool_calls"] for actor, profile in profiles.items()}
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.missing_usage = set()

    def seconds_left(self, *, final: bool = False) -> float:
        reserve = 0 if final else self.final_seconds
        return max(0.0, self.limits["max_elapsed_seconds"] - (self.clock() - self.started) - reserve)

    def reserve_batch(self, requests: dict[str, int]) -> None:
        if requests.keys() & self.reservations.keys():
            raise ValueError("A request reservation cannot be reused.")
        if self.seconds_left() <= 0:
            raise CollaborationBudgetExceeded("Investigation time is exhausted; final time remains reserved.")
        if self.used_requests + len(self.reservations) + len(requests) > self.limits["max_model_requests"]:
            raise CollaborationBudgetExceeded("The shared model-request allowance is exhausted.")
        if self.estimated_tokens + sum(self.reservations.values()) + sum(requests.values()) > self.limits["max_estimated_tokens"]:
            raise CollaborationBudgetExceeded("The shared estimated-token allowance is exhausted.")
        self.reservations.update(requests)

    def consume(self, key: str, estimated_tokens: int) -> None:
        reserved = self.reservations[key]
        if estimated_tokens > reserved:
            raise CollaborationBudgetExceeded("A request exceeds its reserved token capacity.")
        del self.reservations[key]
        self.used_requests += 1
        # Charge the full input estimate and output allowance. Unreported or
        # unexpectedly small API usage never creates extra budget for dispatch.
        self.estimated_tokens += estimated_tokens

    def release(self, key: str) -> None:
        self.reservations.pop(key, None)

    def tools_left(self, actor: str) -> int:
        return min(self.tool_limits[actor] - self.tool_counts[actor],
                   self.limits["max_document_tool_calls"] - sum(self.tool_counts.values()))

    def submit_tool(self, actor: str) -> bool:
        if self.tools_left(actor) <= 0:
            return False
        self.tool_counts[actor] += 1
        return True

    def observe_usage(self, result) -> None:
        for field in self.usage:
            value = getattr(result, field)
            if value is None:
                self.missing_usage.add(field)
            else:
                self.usage[field] += value
        if sum(self.usage.values()) > self.limits["max_estimated_tokens"]:
            raise CollaborationBudgetExceeded("Reported usage exceeds the shared token allowance.")

    def report(self) -> dict:
        return {
            "limits": dict(self.limits), "model_requests": self.used_requests,
            "charged_estimated_tokens": self.estimated_tokens,
            "reserved_model_requests": len(self.reservations),
            "reserved_estimated_tokens": sum(self.reservations.values()),
            "document_tool_calls": dict(self.tool_counts),
            "elapsed_seconds": max(0.0, self.clock() - self.started),
            "reported_usage": {field: None if field in self.missing_usage else value
                               for field, value in self.usage.items()},
        }
