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

    logger.info("Scheduler iniciado. Publicações às 9h, 13h e 17h (horário de Brasília)")
    scheduler.start()


if __name__ == "__main__":
    main()
