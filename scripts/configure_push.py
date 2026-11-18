"""Configure local VAPID keys without printing the private key."""
import argparse
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("contact", help="HTTPS contact page or mailto address for the push provider")
    args = parser.parse_args()
    if not args.contact.startswith(("mailto:", "https://")) or any(c.isspace() for c in args.contact):
        parser.error("Supply a mailto: or https:// contact")
    path = Path(__file__).resolve().parents[1] / ".env"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if any(line.startswith(("CAMPUSFLOW_PUSH_KEY=", "CAMPUSFLOW_PUSH_CONTACT=")) for line in existing.splitlines()):
        parser.error("Push configuration already exists in .env")
    key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    encoded = base64.urlsafe_b64encode(key).decode().rstrip("=")
    with path.open("a", encoding="utf-8") as output:
        output.write(f"\nCAMPUSFLOW_PUSH_KEY={encoded}\nCAMPUSFLOW_PUSH_CONTACT={args.contact}\n")


if __name__ == "__main__":
    main()
