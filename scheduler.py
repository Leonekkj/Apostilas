"""
scheduler.py — Publicação automática de anúncios no Mercado Livre.

Roda 30 anúncios/dia, com 5 segundos de pausa entre cada publicação.
Suporta --dry-run para testar sem publicar.
"""
import sys
import time
import argparse
import logging
import itertools
from apscheduler.schedulers.blocking import BlockingScheduler

import database
from ml import client as ml_client
from ml import orders as ml_orders

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = False
DAILY_LIMIT = 30
PAUSE_BETWEEN = 5  # seconds

_FATIAS = [30, 60, 90, 120, 150, 200]
_PRECOS_PRODUTO = {30: 14.90, 60: 19.90, 90: 24.90, 120: 29.90, 150: 34.90, 200: 44.90}


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


def gerar_kits_automaticos():
    """Gera kits combinando apostilas de tópicos diferentes (2, 3 e 4 por kit).

    Idempotente: kits já existentes são ignorados.
    Roda diariamente às 6h.
    """
    from generator import content as gen_content
    from generator import images as gen_images

    mapa = database.listar_apostilas_por_topico_e_num_ex()
    topicos = list(mapa.keys())

    if len(topicos) < 2:
        logger.info("Kits automáticos: menos de 2 tópicos disponíveis, pulando.")
        return

    logger.info("Kits automáticos: %d tópicos, gerando combinações 2-4", len(topicos))
    kits_criados = 0
    kits_pulados = 0

    for r in [2, 3, 4]:
        if len(topicos) < r:
            continue
        for combo_topicos in itertools.combinations(topicos, r):
            for num_ex in _FATIAS:
                # Verifica se todas as apostilas existem para esse tamanho
                apostila_ids = []
                for topico_id in combo_topicos:
                    aid = mapa.get(topico_id, {}).get(num_ex)
                    if aid is None:
                        break
                    apostila_ids.append(aid)

                if len(apostila_ids) != r:
                    kits_pulados += 1
                    continue

                # Evita duplicatas
                if database.kit_existe(apostila_ids):
                    kits_pulados += 1
                    continue

                try:
                    apostilas_objs = [database.buscar_apostila_por_id(aid) for aid in apostila_ids]
                    nome = gen_content.sugerir_nome_kit(apostilas_objs)
                    kit_id = database.criar_kit(nome, apostila_ids)

                    # Preço: soma individual com 10% de desconto
                    preco_individual = _PRECOS_PRODUTO.get(num_ex, 29.90)
                    preco_kit = round(preco_individual * r * 0.90, 2)

                    total_exercicios = num_ex * r
                    titulos = gen_content.gerar_titulos_kit_ml(nome, apostilas_objs, total_exercicios)
                    topico_kit = {"nome": nome}
                    descricao = gen_content.gerar_descricao_ml(topico_kit, total_exercicios)

                    for i, title in enumerate(titulos, start=1):
                        image_paths = gen_images.gerar_capas_kit(kit_id, nome, apostilas_objs, i)
                        image_path = image_paths[0] if image_paths else None

                        anuncio_id = database.criar_anuncio(
                            None, "fisico", i, title["titulo"], preco_kit,
                            i, title.get("angulo", ""), kit_id, descricao,
                        )
                        if image_path:
                            database.atualizar_anuncio(anuncio_id, imagem_path=image_path)

                    kits_criados += 1
                    logger.info("Kit criado: %s (%d ex, %d apostilas, R$%.2f)", nome, num_ex, r, preco_kit)

                except Exception as e:
                    logger.error("Erro ao criar kit automático (%s, %d ex): %s", combo_topicos, num_ex, e)

    logger.info("Kits automáticos concluído: %d criados, %d pulados", kits_criados, kits_pulados)


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
    # Gera kits automáticos diariamente às 6h
    scheduler.add_job(gerar_kits_automaticos, "cron", hour=6, minute=0)

    logger.info("Scheduler iniciado. Publicações às 9h, 13h e 17h (horário de Brasília)")
    scheduler.start()


if __name__ == "__main__":
    main()
