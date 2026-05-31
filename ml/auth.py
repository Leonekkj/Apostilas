"""OAuth 2.0 authentication for Mercado Livre."""

import os
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
load_dotenv()

# Importa database do diretório pai
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database

# Environment variables
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "http://localhost:8000/api/ml/callback")

# Mercado Livre OAuth URLs
ML_AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


def get_auth_url() -> str:
    """
    Retorna a URL de autorização OAuth 2.0 do Mercado Livre.

    Returns:
        str: URL completa com parâmetros de autorização.
    """
    params = {
        "response_type": "code",
        "client_id": os.getenv("ML_CLIENT_ID", ML_CLIENT_ID),
        "redirect_uri": os.getenv("ML_REDIRECT_URI", ML_REDIRECT_URI).strip(),
    }
    query_string = urlencode(params)
    return f"{ML_AUTH_URL}?{query_string}"


def exchange_code(code: str) -> dict:
    """
    Troca o código de autorização por tokens de acesso e refresh.

    Args:
        code: Código de autorização retornado pela API do Mercado Livre.

    Returns:
        dict: Dicionário com 'access_token', 'refresh_token', 'expires_in' (segundos).

    Raises:
        RuntimeError: Se a API retornar um erro.
    """
    redirect_uri = os.getenv("ML_REDIRECT_URI", ML_REDIRECT_URI).strip()
    payload = {
        "grant_type": "authorization_code",
        "client_id": os.getenv("ML_CLIENT_ID", ML_CLIENT_ID),
        "client_secret": os.getenv("ML_CLIENT_SECRET", ML_CLIENT_SECRET),
        "code": code,
        "redirect_uri": redirect_uri,
    }

    response = requests.post(ML_TOKEN_URL, data=payload)

    if response.status_code != 200:
        error_data = response.json()
        error_msg = error_data.get("message", response.text)
        raise RuntimeError(f"Erro ao trocar código por token: {error_msg}")

    data = response.json()
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in"),
    }


def _is_token_expired(expires_at: str) -> bool:
    """
    Verifica se o token expirou ou expira em menos de 5 minutos.

    Args:
        expires_at: Data/hora de expiração em formato ISO (ex: 2026-05-13T12:30:00).

    Returns:
        bool: True se expirado ou próximo de expirar.
    """
    try:
        expiry = datetime.fromisoformat(expires_at)
        now = datetime.utcnow()
        # Considera expirado se falta menos de 5 minutos
        return now >= (expiry - timedelta(minutes=5))
    except (ValueError, TypeError):
        # Se não conseguir parsear, assume que expirou
        return True


def refresh_token_if_needed() -> str:
    """
    Verifica se o token atual expirou e o renova se necessário.

    Returns:
        str: Token de acesso válido.

    Raises:
        RuntimeError: Se não houver tokens salvos no banco.
        RuntimeError: Se a renovação falhar.
    """
    tokens = database.buscar_ml_tokens()

    if not tokens:
        raise RuntimeError("Token ML não configurado")

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_at = tokens.get("expires_at")

    # Verifica se precisa renovar
    if not _is_token_expired(expires_at):
        return access_token

    # Renova o token
    payload = {
        "grant_type": "refresh_token",
        "client_id": ML_CLIENT_ID,
        "client_secret": ML_CLIENT_SECRET,
        "refresh_token": refresh_token,
    }

    response = requests.post(ML_TOKEN_URL, data=payload)

    if response.status_code != 200:
        error_data = response.json()
        error_msg = error_data.get("message", response.text)
        raise RuntimeError(f"Erro ao renovar token: {error_msg}")

    data = response.json()
    new_access_token = data.get("access_token")
    new_refresh_token = data.get("refresh_token", refresh_token)  # Mantém se não retornar
    expires_in = data.get("expires_in", 21600)  # default 6 horas

    # Calcula expires_at
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

    # Salva novos tokens
    database.salvar_ml_tokens(new_access_token, new_refresh_token, expires_at)

    return new_access_token


def get_valid_token() -> str:
    """
    Retorna um token de acesso válido, renovando se necessário.

    Returns:
        str: Token de acesso válido.

    Raises:
        RuntimeError: Se não houver tokens no banco ou se a renovação falhar.
    """
    return refresh_token_if_needed()
