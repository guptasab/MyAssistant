"""One-shot helper to run Google OAuth and cache the token. `python -m myassistant.tools.google_auth`."""
from myassistant.skills.calendar_skill import _service

if __name__ == "__main__":
    svc = _service()
    if svc:
        print("Google auth OK. Token cached.")
    else:
        print("Failed. Make sure GOOGLE_OAUTH_CLIENT_SECRETS points to a valid OAuth client JSON.")
