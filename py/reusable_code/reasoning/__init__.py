"""Multi-step reasoning on top of reusable_code.ask_question() -- draft, self-check the draft's
claims against its own retrieved excerpts, retrieve again with a refined query and redraft if
unsupported, up to USE_REASONING's REASONING_MAX_STEPS times. See orchestrator.py for the full
explanation of why/when this differs from a plain ask_question() call.

    from reusable_code.reasoning import ask_with_reasoning

    result = ask_with_reasoning("What does the Yoga-Sutra say about ahimsa?")
"""
from .orchestrator import ask_with_reasoning
from .prompts import SELF_CHECK_SYSTEM_PROMPT

__all__ = ["ask_with_reasoning", "SELF_CHECK_SYSTEM_PROMPT"]
