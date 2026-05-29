"""
scheduler.py — Publicação automática de anúncios no Mercado Livre.

Roda 30 anúncios/dia, com 5 segundos de pausa entre cada publicação.
Suporta --dry-run para testar sem publicar.
"""
import sys
import time
import argparse
import logging
from apscheduler.schedulers.blocking import BlockingScheduler

import database
from ml import client as ml_client
from ml import orders as ml_orders

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = False
DAILY_LIMIT = 30
PAUSE_BETWEEN = 5  # seconds


def publicar_batch():
    """Publica até DAILY_LIMIT anúncios rascunho."""
    rascunhos = database.buscar_anuncios_rascunho(limite=DAILY_LIMIT)
    logger.info(f"Batch iniciado: {len(rascunhos)} rascunhos disponíveis")

    publicados = 0
    for anuncio in rascunhos:
        if DRY_RUN:
            logger.info(f"[DRY-RUN] Anúncio {anuncio['id']}: {anuncio['titulo'][:50]}")
            publicados += 1
            time.sleep(0.1)
            continue

        try:
            ml_id = ml_client.publicar_anuncio(anuncio["id"])
            logger.info(f"Publicado: anuncio_id={anuncio['id']} ml_id={ml_id}")
            publicados += 1
        except Exception as e:
            logger.error(f"Erro anuncio {anuncio['id']}: {e}")

        time.sleep(PAUSE_BETWEEN)

    logger.info(f"Batch concluído: {publicados}/{len(rascunhos)} publicados")


def sincronizar_e_gerar_pdfs():
    """Sincroniza pedidos pagos do ML e gera PDFs para apostilas vendidas que ainda não têm."""
    # 1. Sincroniza vendas
    try:
        pedidos = ml_orders.buscar_pedidos_pagos()
        for pedido in pedidos:
            ml_order_id = str(pedido.get("id", ""))
            if not ml_order_id:
                continue
            comprador_nickname = pedido.get("buyer", {}).get("nickname", "")
            data_venda = pedido.get("date_created", "")
            for item in pedido.get("order_items", []):
                ml_item_id = item.get("item", {}).get("id", "")
                valor = float(item.get("unit_price", 0))
                quantidade = int(item.get("quantity", 1))
                anuncio_id = database.buscar_anuncio_id_por_ml_id(ml_item_id)
                database.salvar_venda(
                    ml_order_id=ml_order_id,
                    anuncio_id=anuncio_id,
                    comprador_nickname=comprador_nickname,
                    valor=valor,
                    quantidade=quantidade,
                    data_venda=data_venda,
                )
        logger.info(f"Vendas sincronizadas: {len(pedidos)} pedidos")
    except Exception as e:
        logger.error(f"Erro ao sincronizar vendas: {e}")
        return

    # 2. Gera PDFs para apostilas vendidas sem PDF
    from generator import pdf as pdf_gen
    pendentes = database.buscar_apostilas_vendidas_sem_pdf()
    logger.info(f"Apostilas vendidas sem PDF: {len(pendentes)}")
    for ap in pendentes:
        try:
            import json
            topico = {"nome": ap["topico_nome"]}
            conteudo = json.loads(ap["conteudo_json"]) if ap["conteudo_json"] else {}
            pdf_path = pdf_gen.gerar_pdf(ap["id"], topico, conteudo)
            database.atualizar_pdf_apostila(ap["id"], pdf_path)
            logger.info(f"PDF gerado: apostila_id={ap['id']} path={pdf_path}")
        except Exception as e:
            logger.error(f"Erro ao gerar PDF apostila {ap['id']}: {e}")


def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="Scheduler de publicação de apostilas")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem publicar no ML")
    parser.add_argument("--once", action="store_true", help="Roda uma vez e sai (para testes)")
    args = parser.parse_args()

    if args.dry_run:
        DRY_RUN = True

    database.criar_tabelas()

    if args.once:
        logger.info("Modo --once: executando uma rodada")
        publicar_batch()
        return

    scheduler = BlockingScheduler(timezone="America/Sao_Paulo")
    # Roda às 9h, 13h, 17h (3 batches de 10 = 30/dia)
    for hour in [9, 13, 17]:
        scheduler.add_job(publicar_batch, "cron", hour=hour, minute=0)
    # Sincroniza vendas e gera PDFs a cada hora
    scheduler.add_job(sincronizar_e_gerar_pdfs, "interval", hours=1)

    logger.info("Scheduler iniciado. Publicações às 9h, 13h e 17h (horário de Brasília)")
    scheduler.start()


if __name__ == "__main__":
    main()
