"""Walk the Phase 2 flow against a running API with a real Supabase access token:

    me/onboarding -> create family -> invite a member -> add an elder -> pair a fake phone
    -> call a device-authenticated endpoint

    python scripts/dev_login.py you@example.com            # get a token
    python scripts/demo_flow.py --token <access token> --timezone Asia/Kolkata --country IN

--timezone/--country/--name are only used if your profile isn't onboarded yet (we never
guess them). Talks to http://127.0.0.1:8000 unless --api says otherwise.
"""

import argparse
import asyncio
import sys
from typing import Any

import httpx


class FlowError(Exception):
    pass


def _check(response: httpx.Response, step: str) -> Any:
    if response.status_code >= 400:
        raise FlowError(f"{step} failed: {response.status_code} {response.text}")
    return response.json() if response.content else None


async def run_flow(
    client: httpx.AsyncClient,
    token: str,
    *,
    name: str | None = None,
    timezone: str | None = None,
    country: str | None = None,
    say: Any = print,
) -> dict[str, Any]:
    user = {"Authorization": f"Bearer {token}"}

    me = _check(await client.get("/v1/me", headers=user), "GET /v1/me")
    say(f"1. Signed in as {me['email']} (onboarded: {me['onboarding']['complete']})")
    if not me["onboarding"]["complete"]:
        missing = me["onboarding"]["missing"]
        profile: dict[str, Any] = {"confirm_age_16_plus": True}
        if "display_name" in missing:
            profile["display_name"] = name or me["email"].split("@")[0]
        if "timezone" in missing:
            if not timezone:
                raise FlowError("your profile needs a timezone: pass --timezone")
            profile["timezone"] = timezone
        if "country_code" in missing:
            if not country:
                raise FlowError("your profile needs a country: pass --country")
            profile["country_code"] = country
        me = _check(await client.patch("/v1/me", headers=user, json=profile), "PATCH /v1/me")
        say(f"   Onboarded as {me['display_name']} ({me['timezone']}, {me['country_code']})")

    family = _check(
        await client.post("/v1/families", headers=user, json={"name": "Demo family"}),
        "create family",
    )
    say(f"2. Created family '{family['name']}' ({family['id']}); you are {family['my_role']}")

    invite = _check(
        await client.post(f"/v1/families/{family['id']}/invites", headers=user), "create invite"
    )
    preview = _check(
        await client.post("/v1/invites/preview", headers=user, json={"code": invite["code"]}),
        "preview invite",
    )
    say(f"3. Member invite {invite['code']} -> {invite['link']} (expires {invite['expires_at']})")
    say(f"   Preview: '{preview['family_name']}' invited by {preview['invited_by']}")

    elder = _check(
        await client.post(
            f"/v1/families/{family['id']}/elders",
            headers=user,
            json={
                "display_name": "Demo elder",
                "relation_label": "Mom",
                "timezone": me["timezone"],
                "country_code": me["country_code"],
            },
        ),
        "create elder",
    )
    primary = "yes" if elder["is_primary"] else "no"
    say(f"4. Added elder {elder['display_name']} ({elder['timezone']}), primary: {primary}")

    pairing = _check(
        await client.post(f"/v1/elders/{elder['id']}/pairing-codes", headers=user),
        "create pairing code",
    )
    claim = _check(
        await client.post(
            "/v1/pairing/claim",
            json={"code": pairing["code"], "platform": "android", "device_model": "demo-phone"},
        ),
        "claim pairing code",
    )
    device = {"Authorization": f"Bearer {claim['device_token']}"}
    say(f"5. Paired a fake phone with code {pairing['code']} (device {claim['device']['id']})")

    device_me = _check(await client.get("/v1/device/me", headers=device), "GET /v1/device/me")
    say(
        f"6. As the phone: GET /v1/device/me -> elder '{device_me['elder']['display_name']}' "
        f"in '{device_me['family']['name']}'"
    )
    return {
        "family": family,
        "invite": invite,
        "elder": elder,
        "claim": claim,
        "device_me": device_me,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--token", required=True, help="Supabase access token (dev_login.py)")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--name")
    parser.add_argument("--timezone", help="IANA timezone, e.g. Asia/Kolkata")
    parser.add_argument("--country", help="ISO country code, e.g. IN")
    args = parser.parse_args()

    async def go() -> None:
        async with httpx.AsyncClient(base_url=args.api, timeout=30) as client:
            await run_flow(
                client, args.token, name=args.name, timezone=args.timezone, country=args.country
            )

    try:
        asyncio.run(go())
    except FlowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\nDone: every step of the Phase 2 flow worked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
