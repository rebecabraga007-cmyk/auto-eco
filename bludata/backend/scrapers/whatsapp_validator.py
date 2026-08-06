"""
WhatsApp number validator.
Uses publicly available check endpoints where possible.
Falls back gracefully if unavailable.
"""
import httpx
import asyncio
import re
from typing import Optional


def normalize_phone(phone: str) -> str:
    """Normalize Brazilian phone number to E.164 format (55XXXXXXXXXXX)."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("55") and len(digits) >= 12:
        return digits
    if len(digits) == 11:
        return f"55{digits}"
    if len(digits) == 10:
        # Add 9 for mobile (DDD + 9 digits)
        ddd = digits[:2]
        number = digits[2:]
        return f"55{ddd}9{number}"
    return f"55{digits}"


async def check_whatsapp(phone: str) -> dict:
    """
    Check if a phone number has WhatsApp.

    NOTE: There is no official free public API to verify WhatsApp numbers without
    a WhatsApp Business API account. This function uses best-effort heuristics.

    For production: integrate with WhatsApp Business API, Twilio Lookup, or
    a service like WA.ME or Zenvia.
    """
    normalized = normalize_phone(phone)

    # Heuristic: Brazilian mobile numbers (11-digit with 9 as 3rd digit of number)
    # are very likely to have WhatsApp. We mark as "provável" rather than confirmed.
    digits = re.sub(r"\D", "", phone)
    is_likely_mobile = False

    if len(digits) >= 10:
        # Remove country code if present
        local = digits[2:] if digits.startswith("55") else digits
        if len(local) == 11 and local[2] == "9":
            is_likely_mobile = True
        elif len(local) == 10:
            is_likely_mobile = False  # Landline

    return {
        "sucesso": True,
        "source": "heuristic",
        "phone": normalized,
        "whatsapp": is_likely_mobile,
        "confidence": "low",
        "nota": (
            "Verificação heurística apenas. Para confirmação real, "
            "integre com WhatsApp Business API, Twilio Lookup ou Zenvia."
        ),
    }


async def check_whatsapp_batch(phones: list) -> list:
    """Check multiple numbers concurrently."""
    tasks = [check_whatsapp(p) for p in phones]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = []
    for r in results:
        if isinstance(r, Exception):
            out.append({"sucesso": False, "source": "blocked", "error": str(r)})
        else:
            out.append(r)
    return out
