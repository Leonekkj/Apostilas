"""ml/ads.py — gasto com Product Ads (Publicidade) do Mercado Livre.

A API de Publicidade exige conta anunciante e scope OAuth de advertising.
Se indisponível, retorna aviso e zero importados — o gasto de Ads pode então
ser lançado manualmente (categoria 'ads', origem 'manual') pelo CRUD de despesas.
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ml import auth
import database

ML_API_BASE = "https://api.mercadolibre.com"


def _advertiser_id(headers: dict) -> str | None:
    """Descobre o advertiser de Product Ads do usuário (product_ads)."""
    r = requests.get(
        f"{ML_API_BASE}/advertising/advertisers",
        params={"product_id": "PADS"},
        headers={**headers, "Api-Version": "1"},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    advs = r.json().get("advertisers") or []
    return str(advs[0]["advertiser_id"]) if advs else None


def sincronizar_gasto_ads(inicio: str, fim: str) -> dict:
    """Puxa o gasto diário de campanhas no período e faz upsert em despesas.

    inicio/fim: 'YYYY-MM-DD'. Idempotente por campanha+dia.
    """
    try:
        token = auth.get_valid_token()
    except Exception as e:
        return {"importados": 0, "total": 0.0, "aviso": f"sem token ML: {e}"}

    headers = {"Authorization": f"Bearer {token}"}
    adv = _advertiser_id(headers)
    if not adv:
        return {"importados": 0, "total": 0.0,
                "aviso": "conta sem advertiser de Product Ads ou scope ausente; use lançamento manual"}

    try:
        r = requests.get(
            f"{ML_API_BASE}/advertising/advertisers/{adv}/product_ads/campaigns",
            params={"date_from": inicio, "date_to": fim, "limit": 100,
                    "metrics": "cost", "metrics_summary": "true"},
            headers={**headers, "Api-Version": "1"},
            timeout=20,
        )
        if r.status_code != 200:
            return {"importados": 0, "total": 0.0, "aviso": f"API ads {r.status_code}: {r.text[:120]}"}
        campanhas = r.json().get("results") or []
    except Exception as e:
        return {"importados": 0, "total": 0.0, "aviso": f"falha ao consultar ads: {e}"}

    importados, total = 0, 0.0
    for c in campanhas:
        cost = float((c.get("metrics") or {}).get("cost", 0) or 0)
        if cost <= 0:
            continue
        ref = f"{c.get('id', 'camp')}:{inicio}:{fim}"
        nome = c.get("name") or "Campanha ML Ads"
        try:
            database.upsert_despesa_ads(
                descricao=f"Ads: {nome} ({inicio}..{fim})",
                valor=round(cost, 2), data=fim, ref_externa=ref,
            )
        except Exception as e:
            return {"importados": importados, "total": round(total, 2),
                    "aviso": f"erro ao salvar despesas de ads: {e}"}
        importados += 1
        total += cost

    return {"importados": importados, "total": round(total, 2), "aviso": None}
