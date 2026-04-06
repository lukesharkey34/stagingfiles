"""
Azure Function — ABM Device Unassign

HTTP-triggered function that receives serial numbers from Power Automate
(originating from a Microsoft Form submission) and calls the Apple Business
Manager API to unassign devices from MDM.
"""

import json
import logging
import os
import re
from typing import Optional

import azure.functions as func

from abm_client import ABMClient, ABMAuthError, ABMAPIError

app = func.FunctionApp()

logger = logging.getLogger(__name__)

LIMITATION_NOTICE = (
    "Devices have been unassigned from MDM management. "
    "If full release/disown from Apple Business Manager is required "
    "(e.g., for buyback), an admin must complete that step manually "
    "in the ABM web portal at business.apple.com."
)


def _get_abm_client() -> ABMClient:
    """Build an ABMClient from environment variables.

    In production, ABM_PRIVATE_KEY_PEM should be a Key Vault reference:
        @Microsoft.KeyVault(SecretUri=https://<vault>.vault.azure.net/secrets/abm-private-key/)

    For local development, paste the PEM content directly into local.settings.json.
    If KEY_VAULT_URL and KEY_VAULT_SECRET_NAME are set, the function will fetch
    the private key from Key Vault instead.
    """
    client_id = os.environ["ABM_CLIENT_ID"]
    key_id = os.environ["ABM_KEY_ID"]

    # Try Key Vault first, fall back to direct env var
    private_key_pem = _load_private_key()

    return ABMClient(client_id=client_id, key_id=key_id, private_key_pem=private_key_pem)


def _load_private_key() -> str:
    """Load the ABM private key from Key Vault or environment variable."""
    vault_url = os.environ.get("KEY_VAULT_URL")
    secret_name = os.environ.get("KEY_VAULT_SECRET_NAME")

    if vault_url and secret_name:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_url, credential=credential)
            secret = client.get_secret(secret_name)
            logger.info("Loaded ABM private key from Key Vault")
            return secret.value
        except Exception as exc:
            logger.warning("Key Vault fetch failed (%s), falling back to env var", exc)

    pem = os.environ.get("ABM_PRIVATE_KEY_PEM", "")
    if not pem:
        raise RuntimeError(
            "ABM private key not configured. Set KEY_VAULT_URL + KEY_VAULT_SECRET_NAME "
            "or ABM_PRIVATE_KEY_PEM environment variable."
        )
    return pem


def _parse_serial_numbers(raw: str) -> list[str]:
    """Parse a raw string of serial numbers into a deduplicated list.

    Accepts comma-separated, semicolon-separated, newline-separated, or any mix.
    Strips whitespace, uppercases, removes blanks, and deduplicates while
    preserving order.
    """
    # Split on commas, semicolons, newlines, or any whitespace-surrounded separator
    parts = re.split(r"[,;\n\r]+", raw)
    seen = set()
    result = []
    for part in parts:
        serial = part.strip().upper()
        if serial and serial not in seen:
            seen.add(serial)
            result.append(serial)
    return result


def _validate_serial(serial: str) -> Optional[str]:
    """Return an error message if the serial looks invalid, else None."""
    if not re.match(r"^[A-Z0-9]{8,14}$", serial):
        return f"Invalid format: expected 8-14 alphanumeric characters, got '{serial}'"
    return None


@app.route(route="unassign-devices", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def unassign_devices(req: func.HttpRequest) -> func.HttpResponse:
    """Unassign devices from MDM via the Apple Business Manager API.

    Expected JSON body:
    {
        "serial_numbers": "SERIAL1, SERIAL2, SERIAL3",
        "submitter_email": "user@company.com",
        "request_id": "<guid>"
    }
    """
    # ── Parse request ──────────────────────────────────────────────
    try:
        body = req.get_json()
    except ValueError:
        return _error_response("Request body must be valid JSON", 400)

    raw_serials = body.get("serial_numbers", "")
    submitter = body.get("submitter_email", "unknown")
    request_id = body.get("request_id", "unknown")

    if not raw_serials or not raw_serials.strip():
        return _error_response("serial_numbers field is required and cannot be empty", 400)

    serials = _parse_serial_numbers(raw_serials)
    if not serials:
        return _error_response("No valid serial numbers found after parsing", 400)

    logger.info(
        "Request %s from %s: %d serial(s) to unassign",
        request_id, submitter, len(serials),
    )

    # ── Validate serial formats ────────────────────────────────────
    results = []
    valid_serials = []

    for serial in serials:
        error = _validate_serial(serial)
        if error:
            results.append({"serial": serial, "status": "invalid", "error": error})
        else:
            valid_serials.append(serial)

    if not valid_serials:
        return _json_response({
            "request_id": request_id,
            "results": results,
            "summary": _build_summary(results),
            "limitation_notice": LIMITATION_NOTICE,
        }, 200)

    # ── Authenticate to ABM ────────────────────────────────────────
    try:
        client = _get_abm_client()
        client.authenticate()
    except ABMAuthError as exc:
        logger.error("ABM authentication failed: %s", exc)
        return _error_response(
            "Failed to authenticate with Apple Business Manager. "
            "Check ABM credential configuration.",
            502,
        )
    except Exception as exc:
        logger.error("ABM client initialization failed: %s", exc)
        return _error_response(f"ABM client error: {exc}", 500)

    # ── Attempt bulk unassign ──────────────────────────────────────
    try:
        activity_id = client.unassign_devices_bulk(valid_serials)
        activity_result = client.poll_activity_completion(activity_id)

        activity_status = activity_result.get("attributes", {}).get("status", "Unknown")

        if activity_status == "Completed":
            for serial in valid_serials:
                results.append({
                    "serial": serial,
                    "status": "unassigned",
                    "activity_id": activity_id,
                })
        elif activity_status == "PartiallyCompleted":
            # Some succeeded, some failed — report bulk result and note partial success
            for serial in valid_serials:
                results.append({
                    "serial": serial,
                    "status": "partial",
                    "activity_id": activity_id,
                    "note": "Bulk operation partially completed. Check ABM portal for per-device status.",
                })
        else:
            # Bulk failed — fall back to per-device attempts
            logger.warning(
                "Bulk unassign failed (status: %s), falling back to per-device",
                activity_status,
            )
            results.extend(_unassign_individually(client, valid_serials))

    except (ABMAPIError, TimeoutError) as exc:
        logger.warning("Bulk unassign error (%s), falling back to per-device", exc)
        results.extend(_unassign_individually(client, valid_serials))

    # ── Return results ─────────────────────────────────────────────
    return _json_response({
        "request_id": request_id,
        "results": results,
        "summary": _build_summary(results),
        "limitation_notice": LIMITATION_NOTICE,
    }, 200)


def _unassign_individually(client: ABMClient, serials: list[str]) -> list[dict]:
    """Fall back to unassigning devices one at a time."""
    results = []
    for serial in serials:
        try:
            # Check if device exists first
            device = client.lookup_device(serial)
            if device is None:
                results.append({
                    "serial": serial,
                    "status": "not_found",
                    "error": "Device not found in Apple Business Manager",
                })
                continue

            activity_id = client.unassign_device(serial)
            activity_result = client.poll_activity_completion(activity_id)
            activity_status = activity_result.get("attributes", {}).get("status", "Unknown")

            if activity_status == "Completed":
                results.append({
                    "serial": serial,
                    "status": "unassigned",
                    "activity_id": activity_id,
                })
            else:
                results.append({
                    "serial": serial,
                    "status": "error",
                    "error": f"Unassign activity finished with status: {activity_status}",
                    "activity_id": activity_id,
                })

        except Exception as exc:
            logger.error("Failed to unassign %s: %s", serial, exc)
            results.append({
                "serial": serial,
                "status": "error",
                "error": str(exc),
            })

    return results


def _build_summary(results: list[dict]) -> dict:
    """Build a summary count of result statuses."""
    summary = {"total": len(results), "succeeded": 0, "not_found": 0, "failed": 0, "invalid": 0}
    for r in results:
        status = r["status"]
        if status == "unassigned":
            summary["succeeded"] += 1
        elif status == "not_found":
            summary["not_found"] += 1
        elif status == "invalid":
            summary["invalid"] += 1
        else:
            summary["failed"] += 1
    return summary


def _json_response(data: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(data, indent=2),
        status_code=status_code,
        mimetype="application/json",
    )


def _error_response(message: str, status_code: int) -> func.HttpResponse:
    return _json_response({"status": "error", "message": message}, status_code)
