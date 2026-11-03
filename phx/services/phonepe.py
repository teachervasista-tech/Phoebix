"""PhonePe Standard Checkout gateway (HTTP only; no persistence)."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import PaymentGatewayError


def config_from_env():
    environment = os.environ.get("PHONEPE_ENV", "sandbox").lower()
    if environment not in ("sandbox", "production"):
        raise PaymentGatewayError("PHONEPE_ENV must be 'sandbox' or 'production'.")
    values = {"client_id": os.environ.get("PHONEPE_CLIENT_ID", ""),
              "client_secret": os.environ.get("PHONEPE_CLIENT_SECRET", ""),
              "client_version": os.environ.get("PHONEPE_CLIENT_VERSION", "")}
    if environment == "sandbox":
        api_base = "https://api-preprod.phonepe.com/apis/pg-sandbox"
        token_url = f"{api_base}/v1/oauth/token"
    else:
        api_base = "https://api.phonepe.com/apis/pg"
        token_url = "https://api.phonepe.com/apis/identity-manager/v1/oauth/token"
    return {**values, "environment": environment, "api_base": api_base, "token_url": token_url,
            "configured": all(values.values())}


def http_request(url, method="GET", headers=None, body=None):
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        try:
            details = json.loads(error.read().decode("utf-8", errors="replace"))
            message = details.get("message") or details.get("code") or f"HTTP {error.code}"
        except (json.JSONDecodeError, AttributeError):
            message = f"HTTP {error.code}"
        raise PaymentGatewayError(f"PhonePe request failed: {message}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PaymentGatewayError("PhonePe could not be reached. Online payments need an internet connection.") from error
    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise PaymentGatewayError("PhonePe returned an invalid response.") from error
    if not isinstance(result, dict):
        raise PaymentGatewayError("PhonePe returned an unexpected response.")
    return result


class PhonePeGateway:
    def __init__(self, transport=http_request, config_loader=config_from_env):
        self._transport, self._config_loader = transport, config_loader
        self._token, self._expires = None, 0.0

    def is_configured(self):
        try:
            return self._config_loader()["configured"]
        except PaymentGatewayError:
            return False

    def _access_token(self, config):
        if self._token and time.time() < self._expires:
            return self._token
        body = urllib.parse.urlencode({"client_id": config["client_id"], "client_secret": config["client_secret"],
                                       "client_version": config["client_version"],
                                       "grant_type": "client_credentials"}).encode("ascii")
        response = self._transport(config["token_url"], "POST",
                                   {"Content-Type": "application/x-www-form-urlencoded"}, body)
        token = response.get("access_token")
        if not isinstance(token, str) or not token:
            raise PaymentGatewayError("PhonePe did not return an authorization token.")
        expires = response.get("expires_at")
        self._token = token
        self._expires = float(expires) - 60 if isinstance(expires, (int, float)) else time.time() + 300
        return token

    def _call(self, path, method="GET", payload=None):
        config = self._config_loader()
        if not config["configured"]:
            raise PaymentGatewayError("PhonePe is not configured. Set PHONEPE_CLIENT_ID, PHONEPE_CLIENT_SECRET and "
                                      "PHONEPE_CLIENT_VERSION in the .env file, then restart Phoebix.")
        headers = {"Authorization": "O-Bearer " + self._access_token(config), "Content-Type": "application/json"}
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        return self._transport(config["api_base"] + path, method, headers, body)

    def create_order(self, merchant_order_id, amount_paise, reference):
        order = self._call("/checkout/v2/pay", "POST", {
            "merchantOrderId": merchant_order_id, "amount": amount_paise, "expireAfter": 1200,
            "paymentFlow": {"type": "PG_CHECKOUT", "merchantUrls": {"redirectUrl": os.environ.get("PHOEBIX_RETURN_URL", "https://www.phonepe.com/")}},
            "metaInfo": {"udf1": reference[:256]}})
        url, provider_id = order.get("redirectUrl"), order.get("orderId")
        if not isinstance(url, str) or not url.startswith("https://") or not isinstance(provider_id, str):
            raise PaymentGatewayError("PhonePe did not return a valid checkout session.")
        return url, provider_id

    def order_status(self, merchant_order_id):
        result = self._call(f"/checkout/v2/order/{urllib.parse.quote(merchant_order_id, safe='')}/status?details=false")
        details = result.get("paymentDetails") or []
        first = details[0] if details and isinstance(details[0], dict) else {}
        return {"state": str(result.get("state") or "PENDING"), "amount": result.get("amount"),
                "transactionId": first.get("transactionId"), "mode": first.get("paymentMode")}
