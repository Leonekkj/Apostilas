"""classificar_catalogo.py — preenche os metadados meta_* de todos os anúncios
publicados, criando a fonte única que alimenta os exportadores multi-plataforma.

- Com vínculo no banco (kit_id/apostila_id): metadados vêm da estrutura (fonte='banco')
- Órfãos (importados): classificados pelo Groq lendo título+descrição (fonte='groq')

Idempotente: por padrão pula quem já tem meta_classificado_em. Use --reclassificar
para refazer. Log em output/classificacao_catalogo.txt.
"""
import argparse
import json
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
load_dotenv()

import database
from ml import auth
from classificador import classificar

CACA = {"caca-palavras"}


def _conteudo_por_dificuldade(dificuldade) -> str:
    return "caca_palavras" if dificuldade else "cognitivo"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reclassificar", action="store_true", help="refaz mesmo já classificados")
    ap.add_argument("--limite", type=int, default=0, help="limita nº de órfãos (teste)")
    args = ap.parse_args()

    database.criar_tabelas()  # garante colunas meta_*

    log = open("output/classificacao_catalogo.txt", "w", encoding="utf-8")
    def w(s):
        print(s); log.write(s + "\n"); log.flush()

    agora = datetime.utcnow().isoformat()

    # ---- 1. ESTRUTURAL: anúncios com vínculo no banco ----------------------
    with database._get_conn() as conn:
        cur = database._cursor(conn)
        filtro = "" if args.reclassificar else "AND an.meta_classificado_em IS NULL"
        cur.execute(f"""
            SELECT an.id, an.kit_id, an.apostila_id, ap.num_exercicios AS nx,
                   p.dificuldade, k.apostila_ids
            FROM anuncios an
            LEFT JOIN apostilas ap ON an.apostila_id = ap.id
            LEFT JOIN produtos p ON ap.produto_id = p.id
            LEFT JOIN kits k ON an.kit_id = k.id
            WHERE an.status='publicado' AND an.ml_id IS NOT NULL
              AND (an.kit_id IS NOT NULL OR an.apostila_id IS NOT NULL)
              {filtro}
        """)
        estruturais = database._rows_to_dicts(cur.fetchall(), cur)

    n_estrut = 0
    for r in estruturais:
        if r.get("kit_id"):
            try:
                comp = json.loads(r.get("apostila_ids") or "[]")
                napost = max(2, len(comp))
            except Exception:
                napost = 2
            meta = {"tipo_oferta": "kit", "conteudo": "misto", "num_apostilas": napost,
                    "num_exercicios": (r.get("nx") or 60) * napost, "composicao": "", "fonte": "banco"}
        else:
            meta = {"tipo_oferta": "individual",
                    "conteudo": _conteudo_por_dificuldade(r.get("dificuldade")),
                    "num_apostilas": 1, "num_exercicios": r.get("nx") or 60,
                    "composicao": "", "fonte": "banco"}
        database.atualizar_anuncio(
            r["id"], meta_tipo_oferta=meta["tipo_oferta"], meta_conteudo=meta["conteudo"],
            meta_num_apostilas=meta["num_apostilas"], meta_num_exercicios=meta["num_exercicios"],
            meta_composicao=meta["composicao"], meta_fonte="banco", meta_classificado_em=agora,
        )
        n_estrut += 1
    w(f"estruturais classificados (fonte=banco): {n_estrut}")

    # ---- 2. GROQ: órfãos importados ----------------------------------------
    with database._get_conn() as conn:
        cur = database._cursor(conn)
        filtro = "" if args.reclassificar else "AND meta_classificado_em IS NULL"
        cur.execute(f"""
            SELECT id, ml_id, titulo FROM anuncios
            WHERE status='publicado' AND ml_id IS NOT NULL
              AND apostila_id IS NULL AND kit_id IS NULL {filtro}
            ORDER BY id
        """)
        orfaos = database._rows_to_dicts(cur.fetchall(), cur)
    if args.limite:
        orfaos = orfaos[:args.limite]
    w(f"órfãos a classificar via Groq: {len(orfaos)}")

    token = auth.get_valid_token()
    H = {"Authorization": f"Bearer {token}"}
    ok = baixa_conf = err = 0
    for i, o in enumerate(orfaos):
        if i and i % 50 == 0:
            w(f"... {i}/{len(orfaos)} (ok={ok} baixa_conf={baixa_conf} err={err})")
        try:
            r = requests.get(f"https://api.mercadolibre.com/items/{o['ml_id']}/description",
                             headers=H, timeout=15)
            desc = r.json().get("plain_text", "") if r.status_code == 200 else ""
            meta = classificar(o["titulo"], desc)
            database.atualizar_anuncio(
                o["id"], meta_tipo_oferta=meta["tipo_oferta"], meta_conteudo=meta["conteudo"],
                meta_num_apostilas=meta["num_apostilas"], meta_num_exercicios=meta["num_exercicios"],
                meta_composicao=meta["composicao"], meta_fonte="groq", meta_classificado_em=agora,
            )
            ok += 1
            if meta["confianca"] == "baixa":
                baixa_conf += 1
                w(f"BAIXA_CONF {o['ml_id']}: {o['titulo'][:50]}")
        except Exception as e:
            err += 1
            w(f"ERRO {o['ml_id']}: {str(e)[:120]}")
        time.sleep(0.3)

    w(f"FIM: estruturais={n_estrut} | groq_ok={ok} (baixa_conf={baixa_conf}) | erros={err}")
    log.close()


if __name__ == "__main__":
    main()
