from __future__ import annotations

from app.services.storage import load_settings_file, save_settings_file


def load_immich_settings(user_key: str) -> dict:
    data = load_settings_file(user_key)
    api_key = str(data.get("immich_api_key") or "")
    api_url = str(data.get("immich_api_url") or "").strip()
    return {
        "api_url": api_url,
        "api_key": api_key,
        "verify_ssl": data.get("immich_verify_ssl", True) is not False,
        "configured": bool(api_url and api_key),
    }


def save_immich_settings(user_key: str, api_url: str, api_key: str | None, verify_ssl: bool = True) -> dict:
    current = load_settings_file(user_key)
    current["immich_api_url"] = api_url.strip()
    if api_key is not None:
        current["immich_api_key"] = api_key.strip()
    current["immich_verify_ssl"] = verify_ssl
    save_settings_file(user_key, current)
    return load_immich_settings(user_key)
