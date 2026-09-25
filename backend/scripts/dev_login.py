"""Get a Supabase access token for trying the API from /docs (Authorize -> SupabaseJWT).

    python scripts/dev_login.py you@example.com
        Emails you a sign-in link and waits: click it, and the token is caught by a small page
        on http://localhost:3000 (Supabase's default redirect) and printed here.
    python scripts/dev_login.py you@example.com --code 123456
    python scripts/dev_login.py you@example.com --link "https://<ref>.supabase.co/auth/v1/verify?..."
        Finish with what the email contains, without clicking (no new email is sent). A code is
        only in the email if the Magic Link template includes {{ .Token }}.
    python scripts/dev_login.py you@example.com --password
        For a user created with a password (Dashboard > Authentication > Add user).

Needs SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in backend/.env. Supabase's built-in email only
delivers to your project team's addresses and only a few emails per hour.
REST API: https://github.com/supabase/auth#post-otp
"""

import argparse
import getpass
import json
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx

from nodly.config import get_settings

CATCHER_HOST, CATCHER_PORT = "127.0.0.1", 3000
REDIRECT_TO = f"http://localhost:{CATCHER_PORT}"
WAIT_SECONDS = 600

# The sign-in link redirects here with the session in the URL fragment, which only the
# browser sees; this page posts it back to the script.
CATCHER_PAGE = b"""<!doctype html><meta charset="utf-8"><title>Nodly dev login</title>
<body style="font: 18px system-ui; margin: 3em">
<p id="msg">Signing you in...</p>
<script>
const params = new URLSearchParams(location.hash.slice(1));
const msg = document.getElementById("msg");
const done = "Signed in. Go back to the terminal; you can close this tab.";
if (params.get("access_token")) {
  fetch("/session", {method: "POST", body: JSON.stringify(Object.fromEntries(params))})
    .then(() => { msg.textContent = done; });
} else {
  const why = params.get("error_description") || "no token in the link";
  msg.textContent = "Sign-in failed: " + why;
}
</script>"""


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


class _Catcher(BaseHTTPRequestHandler):
    session: dict[str, str] | None = None
    received = threading.Event()

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(CATCHER_PAGE)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        if isinstance(payload, dict) and payload.get("access_token"):
            _Catcher.session = {str(k): str(v) for k, v in payload.items()}
            _Catcher.received.set()
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args: object) -> None:  # keep the terminal quiet
        pass


def wait_for_click() -> dict[str, str] | None:
    try:
        server = HTTPServer((CATCHER_HOST, CATCHER_PORT), _Catcher)
    except OSError as exc:
        raise RuntimeError(
            f"port {CATCHER_PORT} is busy ({exc}); use --link or --code instead"
        ) from exc
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _Catcher.received.wait(WAIT_SECONDS)
    finally:
        server.shutdown()
    return _Catcher.session


def session_from_link(http: httpx.Client, link: str) -> dict[str, str]:
    """Open the email's link without following the redirect: the tokens are in its fragment."""
    response = http.get(link.strip(), follow_redirects=False)
    location = response.headers.get("location", "")
    fragment = parse_qs(urlsplit(location).fragment)
    if "access_token" not in fragment:
        error = fragment.get("error_description", [location or response.text])
        raise RuntimeError(f"the link didn't sign you in: {error[0]}")
    return {key: values[0] for key, values in fragment.items()}


def copy_to_clipboard(text: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("ascii"), check=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def sign_in(args: argparse.Namespace, auth_url: str, http: httpx.Client) -> dict[str, str]:
    if args.password:
        response = http.post(
            f"{auth_url}/token",
            params={"grant_type": "password"},
            json={"email": args.email, "password": getpass.getpass("Password: ")},
        )
    elif args.code:
        response = http.post(
            f"{auth_url}/verify", json={"type": "email", "email": args.email, "token": args.code}
        )
    elif args.link:
        return session_from_link(http, args.link)
    else:
        sent = http.post(
            f"{auth_url}/otp",
            params={"redirect_to": REDIRECT_TO},
            json={"email": args.email, "create_user": True},
        )
        if sent.status_code >= 400:
            raise RuntimeError(f"Supabase refused to send the email: {sent.text}")
        print(f"Sent a sign-in email to {args.email}. Click the link in it (on this computer).")
        print(f"Waiting up to {WAIT_SECONDS // 60} minutes... (Ctrl+C to stop)")
        session = wait_for_click()
        if session is None:
            raise RuntimeError("no sign-in arrived; try again or use --link")
        return session
    if response.status_code >= 400:
        raise RuntimeError(f"sign-in failed: {response.text}")
    return response.json()  # type: ignore[no-any-return]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    how = parser.add_mutually_exclusive_group()
    how.add_argument("--code", help="the 6-digit code from the email")
    how.add_argument("--link", help="the sign-in link from the email (don't click it)")
    how.add_argument("--password", action="store_true", help="sign in with a password")
    parser.add_argument("--quiet", action="store_true", help="print only the token")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_publishable_key:
        return fail("set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY in backend/.env")
    auth_url = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    with httpx.Client(headers={"apikey": settings.supabase_publishable_key}, timeout=20) as http:
        try:
            session = sign_in(args, auth_url, http)
        except RuntimeError as exc:
            return fail(str(exc))

    token = session["access_token"]
    if args.quiet:
        print(token)
        return 0
    expires_in = int(session.get("expires_in", 3600))
    print(f"\nAccess token for {args.email} (valid about {expires_in // 60} minutes):\n")
    print(token)
    copied = copy_to_clipboard(token)
    print(
        f"\n{'Copied to the clipboard. ' if copied else ''}In /docs click Authorize and paste it "
        f"under SupabaseJWT. Signed in at {datetime.now(UTC):%H:%M} UTC."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
