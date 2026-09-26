"""Help's ladder tick and its notifications (CLAUDE.md §8). English copy for now."""

import logging
import uuid
from typing import Any

from nodly.clock import utcnow
from nodly.help.service import NOTIFY_JOB, add_event, run_help_tick
from nodly.jobs.registry import (
    JobContext,
    PeriodicContext,
    PermanentJobError,
    job_handler,
    periodic_task,
)
from nodly.models import Elder, HelpEventKind, HelpKind, HelpRequest, HelpStatus, User
from nodly.push import Push, deliver, family_tokens_by_user, push_sender

logger = logging.getLogger(__name__)

# The app registers this category with "I'm on it" and "Call" buttons.
ALERT_CATEGORY = "help_alert"


@periodic_task("help.tick", interval=lambda settings: settings.help_tick_seconds)
async def tick(ctx: PeriodicContext) -> None:
    async with ctx.sessionmaker() as session:
        repeats = await run_help_tick(session, ctx.now, ctx.settings)
    if repeats:
        logger.info("help alerts repeated", extra={"repeats": repeats})


def _name(elder: Elder) -> str:
    return elder.relation_label or elder.display_name


def build_push(what: str, request: HelpRequest, elder: Elder, actor: str | None) -> Push | None:
    name = _name(elder)
    test = "Test: " if request.is_test else ""
    data: dict[str, Any] = {
        "request_id": str(request.id),
        "elder_id": str(elder.id),
        "test": request.is_test,
    }
    if what == "alert":
        if request.kind == HelpKind.call_me:
            return Push(
                tokens=[],
                title=f"{name} asked you to call",
                body="Not urgent. Call when you can.",
                channel_id="general",
                data={**data, "type": "help_call_me"},
            )
        return Push(
            tokens=[],
            title=f"{test}{name} pressed Help",
            body="This is a test alert. Tap to see how it looks."
            if request.is_test
            else f'Call {name} now, or tap "I\'m on it".',
            channel_id="help_alerts",
            data={**data, "type": "help"},
            category_id=ALERT_CATEGORY,
        )
    if what == "acknowledged":
        return Push(
            tokens=[],
            title=f"{test}{actor or 'Someone'} is on it",
            body=f"{name}'s Help alert is being handled.",
            channel_id="general",
            data={**data, "type": "help_update"},
        )
    if what == "cancelled":
        return Push(
            tokens=[],
            title=f"{test}{name} is okay now",
            body=f"{name} cancelled the Help alert.",
            channel_id="help_alerts",
            data={**data, "type": "help_update"},
        )
    if what == "resolved":
        return Push(
            tokens=[],
            title=f"{test}{name}'s Help alert is resolved",
            body=f"Closed by {actor or 'a family member'}.",
            channel_id="general",
            data={**data, "type": "help_update"},
            priority="normal",
        )
    return None


@job_handler(NOTIFY_JOB)
async def notify(ctx: JobContext, payload: dict[str, Any]) -> None:
    try:
        request_id = uuid.UUID(payload["request_id"])
        what = str(payload["what"])
    except (KeyError, ValueError) as error:
        raise PermanentJobError(f"Bad payload: {error}") from error

    async with ctx.sessionmaker() as session:
        request = await session.get(HelpRequest, request_id)
        if request is None:
            return
        # A repeat that lost the race with "I'm on it" or "I'm okay now" stays quiet.
        if what == "alert" and request.status != HelpStatus.open:
            return
        elder = await session.get_one(Elder, request.elder_id)
        actor_id = {
            "acknowledged": request.acked_by_user_id,
            "resolved": request.closed_by_user_id,
        }.get(what)
        actor = await session.get(User, actor_id) if actor_id else None
        push = build_push(what, request, elder, actor.display_name if actor else None)
        if push is None:
            raise PermanentJobError(f"Unknown notification {what!r}")

        recipients = [
            (user_id, token)
            for user_id, token in await family_tokens_by_user(session, request.family_id)
            if user_id != actor_id  # whoever acted already knows
        ]
        push = Push(**{**push.__dict__, "tokens": [token for _, token in recipients]})
        tickets = await deliver(session, push_sender(ctx.settings), push)
        if what == "alert":
            accepted = {ticket.token for ticket in tickets if ticket.ok}
            delivered = sorted({str(user_id) for user_id, token in recipients if token in accepted})
            add_event(
                session,
                request.id,
                HelpEventKind.pushed,
                utcnow(),
                data={"delivered": delivered, "tokens": len(recipients)},
            )
        await session.commit()
