"""Shopee Open Platform — autenticação via HMAC-SHA256."""

import hashlib
import hmac
import os
import time
import requests
from typing import Optional

SHOPEE_PARTNER_ID = int(os.getenv("SHOPEE_PARTNER_ID", "0"))
SHOPEE_PARTNER_KEY = os.getenv("SHOPEE_PARTNER_KEY", "")
SHOPEE_SHOP_ID = int(os.getenv("SHOPEE_SHOP_ID", "0"))
SHOPEE_REDIRECT_URI = os.getenv("SHOPEE_REDIRECT_URI", "http://localhost:8000/api/shopee/callback")

SHOPEE_BASE_URL = "https://partner.shopeemobile.com"


def _sign(path: str, timestamp: int, access_token: str = "", shop_id: int = 0) -> str:
    """Gera assinatura HMAC-SHA256 para a Shopee API."""
    base = f"{SHOPEE_PARTNER_ID}{path}{timestamp}{access_token}{shop_id}"
    return hmac.new(
        SHOPEE_PARTNER_KEY.encode(),
        base.encode(),
        hashlib.sha256
    ).hexdigest()


def get_auth_url() -> str:
    """Retorna URL de autorização OAuth da Shopee."""
    timestamp = int(time.time())
    path = "/api/v2/shop/auth_partner"
    sign = _sign(path, timestamp)
    params = (
        f"partner_id={SHOPEE_PARTNER_ID}"
        f"&timestamp={timestamp}"
        f"&sign={sign}"
        f"&redirect={SHOPEE_REDIRECT_URI}"
    )
    return f"{SHOPEE_BASE_URL}{path}?{params}"


def exchange_code(code: str, shop_id: int) -> dict:
    """Troca o código de autorização por access_token e refresh_token."""
    timestamp = int(time.time())
    path = "/api/v2/auth/token/get"
    sign = _sign(path, timestamp)

    r = requests.post(
        f"{SHOPEE_BASE_URL}{path}",
        json={
            "code": code,
            "shop_id": shop_id,
            "partner_id": SHOPEE_PARTNER_ID,
        },
        params={
            "partner_id": SHOPEE_PARTNER_ID,
            "timestamp": timestamp,
            "sign": sign,
        },
        timeout=15,
    )
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"Shopee auth error: {data['error']} — {data.get('message', '')}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expire_in", 14400),
        "shop_id": shop_id,
    }


def refresh_token(refresh_tok: str, shop_id: int) -> dict:
    """Renova o access_token usando o refresh_token."""
    timestamp = int(time.time())
    path = "/api/v2/auth/access_token/get"
    sign = _sign(path, timestamp)

    r = requests.post(
        f"{SHOPEE_BASE_URL}{path}",
        json={
            "refresh_token": refresh_tok,
            "shop_id": shop_id,
            "partner_id": SHOPEE_PARTNER_ID,
        },
        params={
            "partner_id": SHOPEE_PARTNER_ID,
            "timestamp": timestamp,
            "sign": sign,
        },
        timeout=15,
    )
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"Shopee refresh error: {data['error']}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expire_in", 14400),
    }


def get_valid_token() -> tuple[str, int]:
    """
    Retorna (access_token, shop_id) válido, renovando se necessário.
    Lança RuntimeError se não configurado.
    """
    import database
    tokens = database.buscar_shopee_tokens()
    if not tokens:
        raise RuntimeError("Shopee não conectado — faça OAuth primeiro")

    import time
    from datetime import datetime
    expires_at = tokens.get("expires_at", "")
    shop_id = tokens.get("shop_id", SHOPEE_SHOP_ID)

    # Renova se expirado ou próximo de expirar (5 min de margem)
    if expires_at:
        try:
            exp = datetime.fromisoformat(expires_at)
            if (exp - datetime.utcnow()).total_seconds() < 300:
                new = refresh_token(tokens["refresh_token"], shop_id)
                from datetime import timedelta
                new_exp = (datetime.utcnow() + timedelta(seconds=new["expires_in"])).isoformat()
                database.salvar_shopee_tokens(new["access_token"], new["refresh_token"], new_exp, shop_id)
                return new["access_token"], shop_id
        except Exception:
            pass

    return tokens["access_token"], shop_id
