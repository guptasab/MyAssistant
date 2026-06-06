"""One-shot helper to run Google OAuth and cache the token. `python -m ram.tools.google_auth`."""
from ram.skills.calendar_skill import _service

if __name__ == "__main__":
    svc = _service()
    if svc:
        print("Google auth OK. Token cached.")
    else:
        print("Failed. Make sure GOOGLE_OAUTH_CLIENT_SECRETS points to a valid OAuth client JSON.")
