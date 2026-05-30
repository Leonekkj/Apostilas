"""Envia mensagem ao comprador via ML Mensagens API após venda confirmada."""

import os
import requests
from ml import auth

ML_API_BASE = "https://api.mercadolibre.com"


def _seller_id(token: str) -> str:
    r = requests.get(f"{ML_API_BASE}/users/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return str(r.json()["id"])


def enviar_pdf_ao_comprador(ml_order_id: str, comprador_id: str, pdf_url: str, nome_apostila: str) -> bool:
    """
    Envia mensagem com link do PDF ao comprador via ML Mensagens.

    Returns True se enviado com sucesso, False caso contrário.
    """
    try:
        token = auth.get_valid_token()
        seller_id = _seller_id(token)

        mensagem = (
            f"Olá! Obrigado pela compra da {nome_apostila} 🎉\n\n"
            f"Seu PDF está pronto para download:\n{pdf_url}\n\n"
            "O arquivo é otimizado para impressão em A4 — pode imprimir em casa ou em qualquer gráfica.\n"
            "Qualquer dúvida, é só chamar! 😊"
        )

        payload = {
            "from": {"user_id": seller_id},
            "to": {"user_id": comprador_id},
            "order_id": int(ml_order_id),
            "text": mensagem,
        }

        r = requests.post(
            f"{ML_API_BASE}/messages/action_point",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )

        if r.status_code in (200, 201):
            return True

        # Fallback: tenta endpoint alternativo de mensagens por pack/order
        r2 = requests.post(
            f"{ML_API_BASE}/messages/packs/{ml_order_id}/sellers/{seller_id}",
            json={"text": mensagem},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
        return r2.status_code in (200, 201)

    except Exception as e:
        import logging
        logging.warning(f"[messages] Falha ao enviar PDF ao comprador {comprador_id}: {e}")
        return False
