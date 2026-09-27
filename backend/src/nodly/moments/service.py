"""The moments pipeline (CLAUDE.md §9) and qualification for the free day of Plus (§10).

intent (server timestamp) → upload → complete → the worker verifies → published | rejected.
Every step is idempotent: a second "complete" doesn't queue a second check.
"""

import asyncio
import json
import subprocess
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import imagehash
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nodly.billing.access import grant_moment_credit
from nodly.config import Settings
from nodly.family_clock import family_date, family_timezone
from nodly.jobs.queue import enqueue
from nodly.media import path_for
from nodly.models import Moment, MomentKind, MomentStatus

VERIFY_JOB = "moments.verify"
PHOTO_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
# What the app may announce for each kind, and the file extension it's stored under.
CONTENT_TYPES = {
    MomentKind.photo: {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"},
    # Voice notes are AAC in an MP4 (.m4a) file: what expo-audio records on Android and iOS.
    MomentKind.voice: {"audio/mp4": "m4a", "audio/m4a": "m4a", "audio/x-m4a": "m4a"},
}


class RejectReason:
    """Codes the app turns into friendly words."""

    upload_missing = "upload_missing"  # "complete" came, but the file never arrived
    not_a_photo = "not_a_photo"
    not_audio = "not_audio"  # a voice note that isn't playable audio
    too_large = "too_large"
    too_long = "too_long"  # a voice note over the 5-minute limit


class NotQualifyingReason:
    near_duplicate = "near_duplicate"  # looks like a photo shared in the last 90 days
    late = "late"  # checked more than 24 h after it was started
    posted_by_elder = "posted_by_elder"  # §10: only non-elder family members earn the day
    no_family_clock = "no_family_clock"  # the family has no elder yet, so no "day"
    too_short = "too_short"  # a voice note under 10 seconds


def storage_key(moment: Moment, variant: str = "original") -> str:
    extension = CONTENT_TYPES.get(MomentKind(moment.kind), {}).get(moment.content_type, "bin")
    name = f"{variant}.{extension}" if variant == "original" else f"{variant}.jpg"
    return f"{moment.family_id}/{moment.id}/{name}"


async def create_intent(
    session: AsyncSession,
    *,
    family_id: uuid.UUID,
    kind: MomentKind,
    content_type: str,
    now: datetime,
    author_user_id: uuid.UUID | None = None,
    author_device_id: uuid.UUID | None = None,
) -> Moment:
    """Start a moment. Its time, for §10, is now: the server's clock at the intent. Commits."""
    moment = Moment(
        id=uuid.uuid4(),
        family_id=family_id,
        kind=kind,
        status=MomentStatus.awaiting_upload,
        author_user_id=author_user_id,
        author_device_id=author_device_id,
        by_elder=author_device_id is not None,
        intent_at=now,
        content_type=content_type,
        storage_key="",
    )
    moment.storage_key = storage_key(moment)
    session.add(moment)
    await session.commit()
    return moment


async def store_upload(
    settings: Settings, moment: Moment, chunks: AsyncIterator[bytes], limit: int
) -> int:
    """Write the uploaded bytes to the media store (atomically). Returns the size, or -1 if
    it went over `limit` (the partial file is dropped)."""
    target = path_for(settings, moment.storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    size = 0
    with partial.open("wb") as out:
        async for chunk in chunks:
            size += len(chunk)
            if size > limit:
                out.close()
                partial.unlink(missing_ok=True)
                return -1
            out.write(chunk)
    partial.replace(target)
    return size


async def complete(session: AsyncSession, moment: Moment, now: datetime) -> bool:
    """ "I've finished uploading." Queues the check once; later calls change nothing. Returns
    whether this call queued it. Commits."""
    if moment.status != MomentStatus.awaiting_upload:
        return False
    moment.status = MomentStatus.checking
    moment.completed_at = now
    await enqueue(
        session,
        VERIFY_JOB,
        {"moment_id": str(moment.id)},
        run_at=now,
        idempotency_key=str(moment.id),
    )
    await session.commit()
    return True


@dataclass(frozen=True)
class PhotoFacts:
    width: int
    height: int
    content_type: str
    phash: str


def inspect_photo(path: Path, thumbnail: Path, thumbnail_px: int) -> PhotoFacts | None:
    """Open the file as a photo, write a thumbnail, and hash it. None if it isn't a photo."""
    try:
        with Image.open(path) as image:
            image_format = image.format or ""
            if image_format not in PHOTO_TYPES:
                return None
            upright = ImageOps.exif_transpose(image)
            upright.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    small = upright.convert("RGB")
    small.thumbnail((thumbnail_px, thumbnail_px))
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    small.save(thumbnail, "JPEG", quality=82)
    return PhotoFacts(
        width=upright.width,
        height=upright.height,
        content_type=PHOTO_TYPES[image_format],
        phash=str(imagehash.phash(upright)),
    )


def probe_audio(ffprobe: str, path: Path) -> int | None:
    """A voice note's length in milliseconds, measured with ffprobe. None if it isn't an MP4
    audio file we can play: unreadable, another format, no audio, a video, or no duration.
    Blocking; run it in a thread."""
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        info = json.loads(result.stdout)
        streams = info.get("streams", [])
        container = info["format"]["format_name"]
        seconds = float(info["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    has_video = any(
        stream.get("codec_type") == "video"
        and not stream.get("disposition", {}).get("attached_pic")  # cover art is fine
        for stream in streams
    )
    if "mp4" not in container.split(",") or not has_audio or has_video or seconds <= 0:
        return None
    return round(seconds * 1000)


def long_enough(duration_ms: int, settings: Settings) -> bool:
    """A voice note counts for the day from 10 seconds (§10)."""
    return duration_ms >= round(settings.moment_voice_min_seconds * 1000)


async def is_near_duplicate(
    session: AsyncSession, moment: Moment, phash: str, settings: Settings
) -> bool:
    """Close to a photo the family shared in the last 90 days (§10)?"""
    since = moment.intent_at - timedelta(days=settings.moment_duplicate_lookback_days)
    earlier = await session.scalars(
        select(Moment.phash).where(
            Moment.family_id == moment.family_id,
            Moment.id != moment.id,
            Moment.kind == MomentKind.photo,
            Moment.status == MomentStatus.published,
            Moment.deleted_at.is_(None),
            Moment.phash.is_not(None),
            Moment.intent_at >= since,
        )
    )
    mine = imagehash.hex_to_hash(phash)
    return any(
        mine - imagehash.hex_to_hash(other) <= settings.moment_duplicate_max_distance
        for other in earlier
        if other
    )


async def verify(session: AsyncSession, moment: Moment, now: datetime, settings: Settings) -> None:
    """The worker's check: publish or reject, then decide whether it qualifies. Commits."""
    if moment.status != MomentStatus.checking:
        return
    moment.verified_at = now
    path = path_for(settings, moment.storage_key)
    if not path.is_file():
        return await _reject(session, moment, RejectReason.upload_missing)
    size = path.stat().st_size
    if size > max_bytes(moment, settings):
        return await _reject(session, moment, RejectReason.too_large)
    moment.size_bytes = size

    if moment.kind == MomentKind.voice:
        duration_ms = await asyncio.to_thread(probe_audio, settings.ffprobe_path, path)
        if duration_ms is None:
            return await _reject(session, moment, RejectReason.not_audio)
        if duration_ms > settings.moment_voice_max_seconds * 1000:
            return await _reject(session, moment, RejectReason.too_long)
        moment.duration_ms = duration_ms
        moment.content_type = "audio/mp4"
    else:
        thumbnail_key = storage_key(moment, "thumbnail")
        facts = inspect_photo(path, path_for(settings, thumbnail_key), settings.moment_thumbnail_px)
        if facts is None:
            return await _reject(session, moment, RejectReason.not_a_photo)
        moment.width, moment.height, moment.phash = facts.width, facts.height, facts.phash
        moment.content_type = facts.content_type
        moment.thumbnail_key = thumbnail_key

    # Decide everything before assigning: the lookups below autoflush, and a half-set row
    # (qualifies without its day) is refused by a check constraint.
    reason = await _why_not_qualifying(session, moment, now, settings)
    day = None
    if reason is None:
        timezone = await family_timezone(session, moment.family_id)
        assert timezone is not None  # _why_not_qualifying checked it
        day = family_date(moment.intent_at, timezone)
    moment.qualifies = reason is None
    moment.qualifying_local_date = day
    moment.not_qualifying_reason = reason
    moment.status = MomentStatus.published
    moment.published_at = now
    # §10: the family's free day of Plus, in the same transaction as the verdict.
    await grant_moment_credit(session, moment)
    await session.commit()


async def _why_not_qualifying(
    session: AsyncSession, moment: Moment, now: datetime, settings: Settings
) -> str | None:
    if moment.by_elder:
        return NotQualifyingReason.posted_by_elder
    if now - moment.intent_at > timedelta(hours=settings.moment_qualify_within_hours):
        return NotQualifyingReason.late
    if await family_timezone(session, moment.family_id) is None:
        return NotQualifyingReason.no_family_clock
    if moment.kind == MomentKind.voice:
        assert moment.duration_ms is not None
        if not long_enough(moment.duration_ms, settings):
            return NotQualifyingReason.too_short
        return None
    assert moment.phash is not None
    if await is_near_duplicate(session, moment, moment.phash, settings):
        return NotQualifyingReason.near_duplicate
    return None


def max_bytes(moment: Moment, settings: Settings) -> int:
    if moment.kind == MomentKind.voice:
        return settings.moment_voice_max_bytes
    return settings.moment_photo_max_bytes


async def _reject(session: AsyncSession, moment: Moment, reason: str) -> None:
    moment.status = MomentStatus.rejected
    moment.reject_reason = reason
    moment.qualifies = False
    await session.commit()
