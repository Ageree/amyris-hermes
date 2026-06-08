"""One-shot live outbound send — verifies Sendblue creds and that a real
iMessage arrives on the operator's phone (Phase-1A Task 2).

Usage:
    set -a; . ~/.hermes-savedlab/.env; set +a
    python lab/skeleton/scripts/smoke_send.py "$ALLOWED_USER_NUMBER" "$SENDBLUE_FROM_NUMBER"

(or pass the two E.164 numbers explicitly: recipient first, sender second.)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sendblue_client import SendblueClient  # noqa: E402


def main() -> None:
    if len(sys.argv) >= 3:
        to_number, from_number = sys.argv[1], sys.argv[2]
    else:
        to_number = os.environ.get("ALLOWED_USER_NUMBER", "")
        from_number = os.environ.get("SENDBLUE_FROM_NUMBER", "")
    if not (to_number.startswith("+") and from_number.startswith("+")):
        sys.exit("Need E.164 numbers: recipient + sender (argv or ALLOWED_USER_NUMBER/SENDBLUE_FROM_NUMBER env).")
    client = SendblueClient(
        os.environ["SENDBLUE_API_KEY_ID"],
        os.environ["SENDBLUE_API_SECRET_KEY"],
        from_number,
    )
    resp = client.send_message(to_number, "Skeleton smoke ✅ — now reply to test the inbound round-trip.")
    print("sent:", resp)


if __name__ == "__main__":
    main()
