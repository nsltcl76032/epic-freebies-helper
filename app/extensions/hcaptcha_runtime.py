# -*- coding: utf-8 -*-
import asyncio

from hcaptcha_challenger.agent import AgentV
from hcaptcha_challenger.models import ChallengeSignal
from loguru import logger


async def wait_for_challenge_signal(
    agent: AgentV, *, context: str, timeout_seconds: float
) -> ChallengeSignal:
    try:
        signal = await asyncio.wait_for(agent.wait_for_challenge(), timeout=timeout_seconds)
    except Exception as err:
        err_msg = str(err)
        # When challenge frames disappear, close mid-solve, or DOM elements are gone,
        # treat as CHALLENGE_SUCCESS or FAILURE rather than crashing the caller.
        if "Element is not visible or does not exist" in err_msg or "NoneType" in err_msg and "locator" in err_msg:
            logger.warning(
                "hCaptcha challenge frame/element vanished or closed mid-solve | context={} | err={!r}",
                context,
                err,
            )
            return ChallengeSignal.FAILURE
        logger.warning(
            "hCaptcha challenge wait failed | context={} | timeout={}s | err={!r}",
            context,
            timeout_seconds,
            err,
        )
        raise

    logger.info("hCaptcha challenge result | context={} | signal={}", context, signal.value)
    return signal
