"""Shopee Open Platform — publica anúncios na Shopee."""

import hashlib
import hmac
import os
import time
import requests
from pathlib import Path
from typing import Optional

import database
from shopee.auth import SHOPEE_PARTNER_ID, SHOPEE_PARTNER_KEY, SHOPEE_BASE_URL, get_valid_token, _sign

# ID da categoria "Livros e Revistas > Livros Didáticos" na Shopee BR
# https://partner.shopeemobile.com/api/v2/product/get_category
SHOPEE_CATEGORIA_ID = int(os.getenv("SHOPEE_CATEGORIA_ID", "100632"))

# Logística padrão (Normal Delivery)
SHOPEE_LOGISTICA_ID = int(os.getenv("SHOPEE_LOGISTICA_ID", "80003"))


def _api(path: str, payload: dict, access_token: str, shop_id: int) -> dict:
    """Faz POST autenticado para a Shopee API."""
    timestamp = int(time.time())
    sign = _sign(path, timestamp, access_token, shop_id)
    params = {
        "partner_id": SHOPEE_PARTNER_ID,
        "timestamp": timestamp,
        "sign": sign,
        "shop_id": shop_id,
        "access_token": access_token,
    }
    r = requests.post(
        f"{SHOPEE_BASE_URL}{path}",
        params=params,
        json=payload,
        timeout=30,
    )
    return r.json()


def _upload_imagem(imagem_path: str, access_token: str, shop_id: int) -> Optional[str]:
    """Faz upload de imagem e retorna image_id da Shopee."""
    import storage as _storage
    tmp_path = None
    if _storage.is_url(imagem_path):
        try:
            imagem_path = _storage.download_to_temp(imagem_path)
            tmp_path = imagem_path
        except Exception as e:
            print(f"[Shopee] falha ao baixar imagem R2: {e}")
            return None

    if not imagem_path or not Path(imagem_path).exists():
        return None

    timestamp = int(time.time())
    path = "/api/v2/media_space/upload_image"
    sign = _sign(path, timestamp, access_token, shop_id)

    with open(imagem_path, "rb") as f:
        r = requests.post(
            f"{SHOPEE_BASE_URL}{path}",
            params={
                "partner_id": SHOPEE_PARTNER_ID,
                "timestamp": timestamp,
                "sign": sign,
                "shop_id": shop_id,
                "access_token": access_token,
            },
            files={"image": f},
            timeout=30,
        )
    data = r.json()
    return data.get("response", {}).get("image_id")


def publicar_anuncio(anuncio_id: int) -> str:
    """
    Publica um anúncio na Shopee.
    Retorna o item_id da Shopee.
    """
    anuncio = database.buscar_anuncio_por_id(anuncio_id)
    if not anuncio:
        raise RuntimeError(f"Anúncio {anuncio_id} não encontrado")

    access_token, shop_id = get_valid_token()

    # Upload da imagem
    image_ids = []
    img_path = anuncio.get("imagem_path", "")
    img_id = _upload_imagem(img_path, access_token, shop_id)
    if img_id:
        image_ids.append({"image_id": img_id})

    titulo = (anuncio.get("titulo") or "Apostila Cognitiva CogniVita")[:120]
    descricao = anuncio.get("descricao") or ""
    preco = float(anuncio.get("preco") or 0)
    is_digital = anuncio.get("tipo") == "digital"

    payload = {
        "original_price": preco,
        "description": descricao[:3000] if descricao else "Apostila de exercícios cognitivos para idosos.",
        "weight": 0.3,
        "item_name": titulo,
        "category_id": SHOPEE_CATEGORIA_ID,
        "images": image_ids or [{"image_url": ""}],
        "logistics": [{"logistic_id": SHOPEE_LOGISTICA_ID, "enabled": True}],
        "condition": "NEW",
        "item_status": "NORMAL",
        "normal_stock": 999,
        "attribute_list": [],
    }

    # Produto digital — sem envio físico
    if is_digital:
        payload["logistics"] = [{"logistic_id": SHOPEE_LOGISTICA_ID, "enabled": False}]

    data = _api("/api/v2/product/add_item", payload, access_token, shop_id)

    if data.get("error"):
        raise RuntimeError(f"Shopee API error: {data['error']} — {data.get('message', '')}")

    item_id = str(data.get("response", {}).get("item_id", ""))
    if not item_id:
        raise RuntimeError(f"Shopee não retornou item_id: {data}")

    database.atualizar_anuncio(anuncio_id, shopee_item_id=item_id, shopee_status="publicado")
    return item_id
