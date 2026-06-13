"""Envia mensagem ao comprador via ML Mensagens API após venda confirmada."""

import os
import requests
from ml import auth

ML_API_BASE = "https://api.mercadolibre.com"


def _seller_id(token: str) -> str:
    r = requests.get(f"{ML_API_BASE}/users/me", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    return str(r.json()["id"])


def _enviar(ml_order_id: str, comprador_id: str, mensagem: str) -> bool:
    """Envia mensagem ao comprador pela API de mensagens do ML (com fallback de endpoint)."""
    try:
        token = auth.get_valid_token()
        seller_id = _seller_id(token)

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
        logging.warning(f"[messages] Falha ao enviar mensagem ao comprador {comprador_id}: {e}")
        return False


def enviar_pdf_ao_comprador(ml_order_id: str, comprador_id: str, pdf_url: str, nome_apostila: str) -> bool:
    """Envia mensagem com link do PDF ao comprador via ML Mensagens."""
    mensagem = (
        f"Olá! Obrigado pela compra da {nome_apostila} 🎉\n\n"
        f"Seu PDF está pronto para download:\n{pdf_url}\n\n"
        "O arquivo é otimizado para impressão em A4 — pode imprimir em casa ou em qualquer gráfica.\n"
        "Qualquer dúvida, é só chamar! 😊"
    )
    return _enviar(ml_order_id, comprador_id, mensagem)


def enviar_boas_vindas(ml_order_id: str, comprador_id: str) -> bool:
    """Mensagem automática de boas-vindas para venda física nova (<= 350 chars)."""
    mensagem = (
        "Olá! Obrigado pela sua compra 😊 Sua apostila CogniVita é impressa sob demanda, "
        "com capa colorida e encadernação espiral que abre totalmente plana para escrever. "
        "Postamos em até 3 dias úteis com código de rastreio, que você acompanha por aqui. "
        "Qualquer dúvida, é só chamar!"
    )
    return _enviar(ml_order_id, comprador_id, mensagem)
