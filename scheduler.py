"""
scheduler.py — Publicação automática de anúncios no Mercado Livre.

Roda 30 anúncios/dia, com 5 segundos de pausa entre cada publicação.
Suporta --dry-run para testar sem publicar.
"""
import gc
import sys
import time
import argparse
import itertools
import logging

# Carrega .env ANTES de importar database (que lê DATABASE_URL no import) —
# sem isso o scheduler cai em SQLite enquanto a API usa o Postgres do .env
from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.blocking import BlockingScheduler

import database
from ml import client as ml_client
from ml import orders as ml_orders

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = False
DAILY_LIMIT = 30
PAUSE_BETWEEN = 5  # seconds

# Fonte única de preços — pricing.py
import pricing
from pricing import FATIAS as _FATIAS, PRECOS_PRODUTO as _PRECOS_PRODUTO


def _preco_apostila(apostila_id: int, num_exercicios: int) -> float:
    """Retorna o preço real do anúncio individual existente, ou fallback da tabela."""
    # Busca qualquer tipo (fisico, importado) — anúncios importados do ML são a fonte mais confiável
    anuncios = database.listar_anuncios(None, None, None, None, apostila_id, 10)
    for an in anuncios:
        p = float(an.get("preco") or 0)
        if p > 50 and not an.get("kit_id"):
            return p
    return _PRECOS_PRODUTO.get(num_exercicios, 79.99)


def _publicar_anuncios_kit(anuncio_ids: list, kit_nome: str = ""):
    """Publica uma lista de anúncios no ML respeitando PAUSE_BETWEEN entre cada um.
    Pula anúncios com erro de validação anterior ou já publicados."""
    publicados = 0
    for aid in anuncio_ids:
        try:
            anuncio = database.buscar_anuncio_por_id(aid)
            if not anuncio:
                continue
            if anuncio.get("ml_id"):
                continue  # já publicado
            if anuncio.get("erro_msg") and "validation_error" in str(anuncio.get("erro_msg", "")):
                logger.warning("Pulando anúncio %d (validation_error anterior): %s", aid, anuncio.get("erro_msg", "")[:80])
                continue
            ml_id = ml_client.publicar_anuncio(aid)
            logger.info("Publicado anúncio %d → %s (%s)", aid, ml_id, kit_nome)
            publicados += 1
            time.sleep(PAUSE_BETWEEN)
        except Exception as e:
            logger.error("Erro ao publicar anúncio %d (%s): %s", aid, kit_nome, e)
            time.sleep(PAUSE_BETWEEN)
    return publicados


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
        from ml import messages as ml_messages
        pedidos = ml_orders.buscar_pedidos_pagos()
        for pedido in pedidos:
            ml_order_id = str(pedido.get("id", ""))
            if not ml_order_id:
                continue
            comprador_nickname = pedido.get("buyer", {}).get("nickname", "")
            comprador_id = str(pedido.get("buyer", {}).get("id", ""))
            data_venda = pedido.get("date_created", "")
            venda_nova = False
            tipo_anuncio = ""
            for item in pedido.get("order_items", []):
                ml_item_id = item.get("item", {}).get("id", "")
                valor = float(item.get("unit_price", 0))
                quantidade = int(item.get("quantity", 1))
                anuncio_id = database.buscar_anuncio_id_por_ml_id(ml_item_id)
                nova = database.salvar_venda(
                    ml_order_id=ml_order_id,
                    anuncio_id=anuncio_id,
                    comprador_nickname=comprador_nickname,
                    valor=valor,
                    quantidade=quantidade,
                    data_venda=data_venda,
                    comprador_id=comprador_id,
                )
                venda_nova = venda_nova or nova
                if anuncio_id and not tipo_anuncio:
                    an = database.buscar_anuncio_por_id(anuncio_id)
                    tipo_anuncio = (an or {}).get("tipo", "")

            # Boas-vindas automática: só em venda NOVA e física
            # (digital recebe a mensagem própria com o link do PDF via webhook)
            if venda_nova and comprador_id and tipo_anuncio != "digital":
                ok = ml_messages.enviar_boas_vindas(ml_order_id, comprador_id)
                logger.info(f"Boas-vindas venda {ml_order_id}: {'enviada' if ok else 'falhou'}")
                time.sleep(1)
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
            # capa_img: dormente — quando houver arte de IA boa (assets/capas_ia/
            # ou gerador melhor), plugar aqui. Sem ela, sai a capa premium CSS.
            capa_img = None

            if ap.get("dificuldade"):
                # Caça-palavras: gerador próprio (puzzles), NÃO o genérico de exercícios
                from gerar_caca_palavras import gerar_pdf_caca_palavras
                pdf_path = gerar_pdf_caca_palavras(
                    ap["id"],
                    ap.get("produto_nome") or "Caça-Palavras",
                    ap.get("tema") or "geral",
                    ap["dificuldade"],
                    ap.get("num_exercicios") or 60,
                    capa_img=capa_img,
                )
            else:
                topico = {"nome": ap["topico_nome"]}
                # gerar_pdf espera a STRING JSON (faz json.loads internamente)
                conteudo_json = ap["conteudo_json"] or "{}"
                pdf_path = pdf_gen.gerar_pdf(ap["id"], topico, conteudo_json, capa_img=capa_img)
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

    MAX_KITS_POR_EXECUCAO = 20  # limita geração por rodada para controlar memória
    logger.info("Kits automáticos: %d tópicos, gerando combinações 2-4 (max %d/execução)",
                len(topicos), MAX_KITS_POR_EXECUCAO)
    kits_criados = 0
    kits_pulados = 0

    for r in [2, 3, 4]:
        if len(topicos) < r:
            continue
        for combo_topicos in itertools.combinations(topicos, r):
            if kits_criados >= MAX_KITS_POR_EXECUCAO:
                logger.info("Kits automáticos: limite de %d atingido, continuando amanhã.", MAX_KITS_POR_EXECUCAO)
                break
            for num_ex in _FATIAS:
                apostila_ids = []
                for topico_id in combo_topicos:
                    aid = mapa.get(topico_id, {}).get(num_ex)
                    if aid is None:
                        break
                    apostila_ids.append(aid)

                if len(apostila_ids) != r:
                    kits_pulados += 1
                    continue

                if database.kit_existe(apostila_ids):
                    kits_pulados += 1
                    continue

                try:
                    apostilas_objs = [database.buscar_apostila_por_id(aid) for aid in apostila_ids]
                    nome = gen_content.sugerir_nome_kit(apostilas_objs)
                    kit_id = database.criar_kit(nome, apostila_ids)

                    preco_individual = sum(
                        _preco_apostila(aid, num_ex) for aid in apostila_ids
                    )
                    preco_kit = pricing.preco_kit(preco_individual)

                    total_exercicios = num_ex * r
                    titulos = gen_content.gerar_titulos_kit_ml(nome, apostilas_objs, total_exercicios)
                    descricao = gen_content.gerar_descricao_kit_ml(nome, apostilas_objs, total_exercicios)

                    # Gera v1/v2/v3 uma única vez por kit — reutiliza para os 6 anúncios
                    all_image_paths = gen_images.gerar_capas_kit(kit_id, nome, apostilas_objs)

                    novos_anuncio_ids = []
                    for i, title in enumerate(titulos, start=1):
                        variacao_img = ((i - 1) % 3) + 1
                        image_path = next(
                            (p for p in all_image_paths if f"_v{variacao_img}.png" in p),
                            all_image_paths[0] if all_image_paths else None,
                        )
                        anuncio_id = database.criar_anuncio(
                            None, "fisico", i, title["titulo"], preco_kit,
                            i, title.get("angulo", ""), kit_id, descricao,
                        )
                        if image_path:
                            database.atualizar_anuncio(anuncio_id, imagem_path=image_path)
                        novos_anuncio_ids.append(anuncio_id)

                    pub = _publicar_anuncios_kit(novos_anuncio_ids, nome)
                    kits_criados += 1
                    logger.info("Kit criado e publicado: %s (%d ex, %d apostilas, R$%.2f, %d anúncios publicados)", nome, num_ex, r, preco_kit, pub)

                except Exception as e:
                    logger.error("Erro ao criar kit automático (%s, %d ex): %s", combo_topicos, num_ex, e)
                finally:
                    # Libera memória entre kits
                    gc.collect()

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
