"""Ensure a real APP_SECRET_KEY exists in .env before the server starts."""
from pathlib import Path
import secrets

env = Path(".env")
example = Path(".env.example")

if not env.exists():
    if example.exists():
        env.write_text(example.read_text())
    else:
        env.write_text("DATABASE_URL=sqlite:///./data/autonomiq.db\n")

text = env.read_text()
needs_secret = (
    "REPLACE_WITH_LONG_RANDOM_SECRET" in text
    or "unsafe-development-key" in text
    or "APP_SECRET_KEY=" not in text
)
if needs_secret:
    secret = secrets.token_urlsafe(48)
    lines = []
    found = False
    for line in text.splitlines():
        if line.startswith("APP_SECRET_KEY="):
            lines.append(f"APP_SECRET_KEY={secret}")
            found = True
        else:
            lines.append(line)
    if not found:
        lines.append(f"APP_SECRET_KEY={secret}")
    env.write_text("\n".join(lines) + "\n")
    print("Generated a secure APP_SECRET_KEY in .env")
else:
    print("APP_SECRET_KEY already set")
