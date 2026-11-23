"""Keep E/V model-request and estimated-token limits separate from tools.

V starts with its linked E's estimated-token charge. Investigation must leave
one request and a full context window for the final answer. Actual API usage
remains a separate observation; these estimates are not a billing guarantee.
"""


class InvestigationBudgetExhausted(ValueError):
    """End investigation while the protected final request remains available."""


class AgentRequestBudget:
    def __init__(self, settings: dict, *, extractor_estimated_tokens: int = 0):
        self.max_requests = settings.get("max_model_requests")
        self.max_estimated_tokens = settings.get("max_estimated_tokens")
        self.final_context = settings["context_limit"]
        self.extractor_estimated_tokens = extractor_estimated_tokens
        self.requests = 0
        self.estimated_tokens = 0
        if (self.max_estimated_tokens is not None
                and extractor_estimated_tokens + self.final_context > self.max_estimated_tokens):
            raise ValueError("The configuration estimated-token allowance cannot reserve the stage's final answer.")

    def admit(self, estimated_tokens: int, *, final: bool) -> None:
        """Charge once before dispatch; investigation cannot spend the reserve."""
        reserve_requests = 0 if final else 1
        reserve_tokens = 0 if final else self.final_context
        error_type = ValueError if final else InvestigationBudgetExhausted
        if self.max_requests is not None and self.requests + 1 + reserve_requests > self.max_requests:
            raise error_type("The stage model-request allowance is exhausted; the final request is reserved.")
        if (self.max_estimated_tokens is not None
                and self.extractor_estimated_tokens + self.estimated_tokens + estimated_tokens + reserve_tokens
                > self.max_estimated_tokens):
            raise error_type("The configuration estimated-token allowance is exhausted; final capacity is reserved.")
        self.requests += 1
        self.estimated_tokens += estimated_tokens

    def report(self) -> dict:
        return {
            "max_model_requests": self.max_requests,
            "configuration_max_estimated_tokens": self.max_estimated_tokens,
            "extractor_charged_estimated_tokens": self.extractor_estimated_tokens,
            "stage_model_requests": self.requests,
            "stage_charged_estimated_tokens": self.estimated_tokens,
            "configuration_charged_estimated_tokens": self.extractor_estimated_tokens + self.estimated_tokens,
        }
