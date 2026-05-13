"""Mercado Livre client for publishing anuncios (listings)."""

import os
from datetime import datetime
from typing import Optional

import requests

# Importa modules do diretório pai
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database
from ml import auth

# Mercado Livre API URLs
ML_API_BASE = "https://api.mercadolibre.com"
ML_PICTURES_ENDPOINT = f"{ML_API_BASE}/pictures"
ML_ITEMS_ENDPOINT = f"{ML_API_BASE}/items"

# Environment variables
ML_CATEGORIA_ID = os.getenv("ML_CATEGORIA_ID", "MLB174")  # livros/apostilas category


def publicar_anuncio(anuncio_id: int) -> str:
    """
    Publishes a single anuncio to Mercado Livre.

    Args:
        anuncio_id: ID do anúncio no banco de dados.

    Returns:
        str: ML listing ID (ml_id).

    Raises:
        RuntimeError: Se falhar ao publicar ou se dados faltarem.
    """
    # 1. Load anuncio from DB
    anuncio = database.buscar_anuncio_por_id(anuncio_id)
    if anuncio is None:
        raise RuntimeError(f"Anúncio {anuncio_id} não encontrado")

    # 2. Get valid ML token
    try:
        token = auth.get_valid_token()
    except RuntimeError as e:
        raise RuntimeError(f"Token ML não configurado: {e}") from e

    try:
        # 3. Upload cover image if it exists
        picture_id = None
        if anuncio.get("imagem_path"):
            picture_id = _upload_picture(token, anuncio["imagem_path"])

        # 4. Create listing on ML
        ml_id = _create_listing(token, anuncio, picture_id)

        # 5. Update anuncio with success
        now = datetime.utcnow().isoformat()
        database.atualizar_anuncio(
            anuncio_id,
            ml_id=ml_id,
            status="publicado",
            publicado_em=now,
        )

        return ml_id

    except RuntimeError as e:
        # 6. Update anuncio with error
        database.atualizar_anuncio(
            anuncio_id,
            status="erro",
            erro_msg=str(e),
        )
        raise


def _upload_picture(token: str, imagem_path: str) -> str:
    """
    Uploads a cover image to Mercado Livre.

    Args:
        token: Access token do ML.
        imagem_path: Caminho local da imagem.

    Returns:
        str: Picture ID retornado pelo ML.

    Raises:
        RuntimeError: Se falhar ao fazer upload.
    """
    if not os.path.exists(imagem_path):
        raise RuntimeError(f"Imagem não encontrada: {imagem_path}")

    with open(imagem_path, "rb") as f:
        files = {"file": f}
        params = {"access_token": token}

        response = requests.post(ML_PICTURES_ENDPOINT, files=files, params=params)

    if response.status_code != 200:
        error_data = response.json()
        error_msg = error_data.get("message", response.text)
        raise RuntimeError(f"ML API error {response.status_code}: {error_msg}")

    data = response.json()
    return data.get("id")


def _create_listing(token: str, anuncio: dict, picture_id: Optional[str]) -> str:
    """
    Creates a listing on Mercado Livre.

    Args:
        token: Access token do ML.
        anuncio: Dicionário com dados do anúncio (titulo, preco, topico_nome, etc).
        picture_id: ID da imagem (opcional).

    Returns:
        str: ML listing ID (ml_id).

    Raises:
        RuntimeError: Se falhar ao criar listing.
    """
    # Build item payload
    payload = {
        "title": anuncio.get("titulo", ""),
        "category_id": ML_CATEGORIA_ID,
        "price": float(anuncio.get("preco", 0)),
        "currency_id": "BRL",
        "available_quantity": 10,
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_special",
        "condition": "new",
        "description": {
            "plain_text": f"Apostila digital. {anuncio.get('topico_nome', '')}"
        },
        "shipping": {
            "mode": "me2",
            "free_shipping": False,
        },
    }

    # Add pictures if available
    if picture_id:
        payload["pictures"] = [{"id": picture_id}]

    # Add attributes
    attributes = [
        {"id": "EDITORIAL", "value_name": "Cognivita"}
    ]
    if anuncio.get("topico_nome"):
        attributes.append({
            "id": "BOOK_SUBJECT",
            "value_name": anuncio["topico_nome"]
        })
    payload["attributes"] = attributes

    # Make request
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    response = requests.post(ML_ITEMS_ENDPOINT, json=payload, headers=headers)

    if response.status_code != 201:
        error_data = response.json()
        error_msg = error_data.get("message", response.text)
        raise RuntimeError(f"ML API error {response.status_code}: {error_msg}")

    data = response.json()
    return data.get("id")


def pausar_anuncio(anuncio_id: int) -> None:
    """
    Pauses an active ML listing.

    Args:
        anuncio_id: ID do anúncio no banco de dados.

    Raises:
        RuntimeError: Se falhar ao pausar.
    """
    # Load anuncio
    anuncio = database.buscar_anuncio_por_id(anuncio_id)
    if anuncio is None:
        raise RuntimeError(f"Anúncio {anuncio_id} não encontrado")

    ml_id = anuncio.get("ml_id")
    if not ml_id:
        raise RuntimeError(f"Anúncio {anuncio_id} não tem ml_id (não foi publicado)")

    # Get valid token
    try:
        token = auth.get_valid_token()
    except RuntimeError as e:
        raise RuntimeError(f"Token ML não configurado: {e}") from e

    # Pause on ML
    endpoint = f"{ML_ITEMS_ENDPOINT}/{ml_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"status": "paused"}

    response = requests.put(endpoint, json=payload, headers=headers)

    if response.status_code != 200:
        error_data = response.json()
        error_msg = error_data.get("message", response.text)
        raise RuntimeError(f"ML API error {response.status_code}: {error_msg}")

    # Update status locally
    database.atualizar_anuncio(anuncio_id, status="pausado")
