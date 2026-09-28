"""Print which required .env names are still empty. Never prints secret values."""

from __future__ import annotations

from config import missing_settings


def main() -> int:
    missing = missing_settings()
    if not missing:
        print("All required settings are set.")
        return 0
    print("Fill these in workflowgpt/.env:")
    for name in missing:
        print(f"  - {name}")
    print("Put the values in the file. Do not paste secrets into chat.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
