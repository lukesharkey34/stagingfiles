"""
Apple Business Manager API Client

Handles OAuth2 JWT authentication (ES256) and device management operations
for unassigning devices from MDM servers via the ABM API.
"""

import json
import logging
import time
import uuid
from typing import Optional

import jwt
import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key

logger = logging.getLogger(__name__)

TOKEN_URL = "https://account.apple.com/auth/oauth2/token"
ABM_API_BASE = "https://api-business.apple.com/v1"


class ABMAuthError(Exception):
    """Raised when ABM OAuth2 authentication fails."""
    pass


class ABMAPIError(Exception):
    """Raised when an ABM API call fails."""
    def __init__(self, message: str, status_code: int = None, response_body: str = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ABMClient:
    """Client for Apple Business Manager API operations.

    Args:
        client_id: ABM API client ID (e.g., "BUSINESSAPI.xxxxxxxx-xxxx-...")
        key_id: Key ID from ABM API credential
        private_key_pem: PEM-encoded P-256 private key content
    """

    def __init__(self, client_id: str, key_id: str, private_key_pem: str):
        self.client_id = client_id
        self.key_id = key_id
        self._private_key = load_pem_private_key(
            private_key_pem.encode("utf-8") if isinstance(private_key_pem, str) else private_key_pem,
            password=None,
        )
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0
        self._session = requests.Session()

    def authenticate(self) -> str:
        """Obtain an OAuth2 access token using a JWT client assertion.

        Returns the access token string. Tokens are cached and reused until
        they expire (with a 60-second safety margin).
        """
        if self._access_token and time.time() < (self._token_expiry - 60):
            return self._access_token

        assertion = self._build_jwt_assertion()

        resp = self._session.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": assertion,
                "scope": "device.management",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        if resp.status_code != 200:
            raise ABMAuthError(
                f"ABM token request failed with status {resp.status_code}: {resp.text}"
            )

        token_data = resp.json()
        self._access_token = token_data["access_token"]
        self._token_expiry = time.time() + token_data.get("expires_in", 3600)

        logger.info("ABM OAuth2 token acquired, expires in %ds", token_data.get("expires_in", 3600))
        return self._access_token

    def lookup_device(self, serial_number: str) -> Optional[dict]:
        """Look up a device in ABM by serial number.

        Returns the device record dict if found, or None if not found.
        """
        self._ensure_token()

        resp = self._api_get(
            "/orgDevices",
            params={"filter[identifier]": serial_number},
        )

        data = resp.get("data", [])
        if not data:
            return None
        return data[0]

    def unassign_devices_bulk(self, serial_numbers: list[str]) -> str:
        """Unassign multiple devices from MDM in a single API call.

        Args:
            serial_numbers: List of device serial numbers to unassign.

        Returns:
            The activity ID for tracking the operation status.
        """
        self._ensure_token()

        device_identifiers = [
            {"identifier": sn, "identifierType": "SerialNumber"}
            for sn in serial_numbers
        ]

        payload = {
            "data": {
                "type": "orgDeviceActivities",
                "attributes": {
                    "activityType": "Unassign",
                    "deviceIdentifiers": device_identifiers,
                },
            }
        }

        resp = self._api_post("/orgDeviceActivities", payload)
        activity_id = resp["data"]["id"]

        logger.info(
            "Bulk unassign activity created: %s for %d devices",
            activity_id,
            len(serial_numbers),
        )
        return activity_id

    def unassign_device(self, serial_number: str) -> str:
        """Unassign a single device from MDM.

        Returns the activity ID.
        """
        return self.unassign_devices_bulk([serial_number])

    def check_activity_status(self, activity_id: str) -> dict:
        """Check the status of an unassign activity.

        Returns a dict with keys: id, status, and any result details.
        """
        self._ensure_token()
        resp = self._api_get(f"/orgDeviceActivities/{activity_id}")
        return resp.get("data", {})

    def poll_activity_completion(
        self,
        activity_id: str,
        timeout_seconds: int = 30,
        poll_interval: int = 3,
    ) -> dict:
        """Poll an activity until it completes or times out.

        Returns the final activity status dict.

        Raises:
            TimeoutError: If the activity doesn't complete within timeout_seconds.
        """
        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            status = self.check_activity_status(activity_id)
            activity_status = status.get("attributes", {}).get("status", "")

            if activity_status in ("Completed", "Failed", "PartiallyCompleted"):
                logger.info("Activity %s finished with status: %s", activity_id, activity_status)
                return status

            logger.debug("Activity %s status: %s, polling again...", activity_id, activity_status)
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Activity {activity_id} did not complete within {timeout_seconds}s"
        )

    # ── Internal helpers ──────────────────────────────────────────────

    def _build_jwt_assertion(self) -> str:
        """Build a signed JWT client assertion for OAuth2 token exchange."""
        now = int(time.time())
        claims = {
            "iss": self.client_id,
            "sub": self.client_id,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 180,
            "jti": str(uuid.uuid4()),
        }
        headers = {
            "kid": self.key_id,
            "alg": "ES256",
        }
        return jwt.encode(claims, self._private_key, algorithm="ES256", headers=headers)

    def _ensure_token(self) -> None:
        """Ensure we have a valid access token, refreshing if needed."""
        self.authenticate()

    def _api_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _api_get(self, path: str, params: dict = None) -> dict:
        url = f"{ABM_API_BASE}{path}"
        resp = self._session.get(
            url, headers=self._api_headers(), params=params, timeout=30
        )
        if resp.status_code == 404:
            return {"data": []}
        if resp.status_code != 200:
            raise ABMAPIError(
                f"GET {path} failed: {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )
        return resp.json()

    def _api_post(self, path: str, payload: dict) -> dict:
        url = f"{ABM_API_BASE}{path}"
        resp = self._session.post(
            url, headers=self._api_headers(), json=payload, timeout=30
        )
        if resp.status_code not in (200, 201, 202):
            raise ABMAPIError(
                f"POST {path} failed: {resp.status_code}",
                status_code=resp.status_code,
                response_body=resp.text,
            )
        return resp.json()
