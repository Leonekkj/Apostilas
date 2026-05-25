"""Mercado Livre Orders API client — busca pedidos pagos do vendedor."""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml import auth

ML_API_BASE = "https://api.mercadolibre.com"


def buscar_pedidos_pagos() -> list[dict]:
    """Retorna todos os pedidos com status 'paid' do vendedor autenticado.

    Pagina automaticamente até buscar todos os resultados.
    Cada item da lista é um dict com os campos brutos da ML Orders API:
      id, date_created, buyer.nickname, order_items[].item.id,
      order_items[].unit_price, order_items[].quantity
    """
    token = auth.get_valid_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Obtém user_id do vendedor
    me = requests.get(f"{ML_API_BASE}/users/me", headers=headers, timeout=15)
    if me.status_code != 200:
        raise RuntimeError(f"Erro ao buscar dados do usuário ML: {me.text[:200]}")
    user_id = me.json()["id"]

    pedidos: list[dict] = []
    offset = 0
    limit = 50

    while True:
        r = requests.get(
            f"{ML_API_BASE}/orders/search",
            params={
                "seller": user_id,
                "order.status": "paid",
                "offset": offset,
                "limit": limit,
            },
            headers=headers,
            timeout=15,
        )
        if r.status_code != 200:
            raise RuntimeError(f"Erro ao buscar pedidos ML: {r.text[:200]}")

        data = r.json()
        results = data.get("results", [])
        pedidos.extend(results)

        total = data.get("paging", {}).get("total", 0)
        offset += len(results)
        if offset >= total or not results:
            break

    return pedidos
