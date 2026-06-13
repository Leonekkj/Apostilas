"""exportador.py — camada única de exportação multi-plataforma.

Fonte da verdade: o banco enriquecido (anuncios + metadados meta_*).
Cada plataforma é um PERFIL (filtro + ajuste de preço + gerador de arquivo).
Adicionar plataforma = adicionar um perfil, sem reescrever a leitura do catálogo.

Uso:
    python exportador.py --plataforma shopee --limite 50
    python exportador.py --plataforma amazon   (requer GTIN/conta — ver _PERFIS)
"""
import argparse
import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import database

# Fatores de preço por plataforma (comissão/frete diferem do ML).
# 1.00 = mesmo preço do ML. Ajuste fino conforme a taxa real de cada uma.
FATOR_PRECO = {
    "ml":     1.00,
    "shopee": 1.00,   # Shopee tem comissão menor; manter igual por ora
    "amazon": 1.15,   # Amazon cobra mais; sobe-se para preservar margem
}


def carregar_catalogo(somente_classificados: bool = True) -> list:
    """Catálogo unificado dos anúncios publicados, com metadados e preço real do ML."""
    with database._get_conn() as conn:
        cur = database._cursor(conn)
        filtro = "AND an.meta_classificado_em IS NOT NULL" if somente_classificados else ""
        cur.execute(f"""
            SELECT an.id, an.ml_id, an.titulo, an.descricao, an.preco, an.imagem_path,
                   an.meta_tipo_oferta, an.meta_conteudo, an.meta_num_apostilas,
                   an.meta_num_exercicios, an.meta_composicao
            FROM anuncios an
            WHERE an.status='publicado' AND an.ml_id IS NOT NULL
              AND an.imagem_path LIKE 'http%'
              {filtro}
            ORDER BY an.id
        """)
        return database._rows_to_dicts(cur.fetchall(), cur)


def preco_plataforma(preco_ml: float, plataforma: str) -> float:
    return round(float(preco_ml or 0) * FATOR_PRECO.get(plataforma, 1.0), 2)


def _descricao_rica(item: dict) -> str:
    """Descrição comercial coerente com os metadados (não promete o que não entrega)."""
    if (item.get("descricao") or "").strip() and len(item["descricao"].strip()) > 40:
        return item["descricao"].strip()[:4999]
    nap = item.get("meta_num_apostilas") or 1
    nex = item.get("meta_num_exercicios") or 60
    plural = "apostilas físicas impressas" if nap > 1 else "apostila física impressa"
    return (
        f"{item.get('titulo') or 'Apostila CogniVita'}\n\n"
        f"Você recebe {nap} {plural}, com {nex} exercícios no total.\n\n"
        "✅ Estimulação cognitiva para idosos 60+\n"
        "✅ Fonte ampliada, fácil leitura\n"
        "✅ Formato A4, capa colorida, encadernação espiral\n"
        "✅ Gabarito incluído\n\n"
        "Enviado com embalagem protetora e código de rastreio."
    )


# ---------------------------------------------------------------------------
# Perfil Shopee — reaproveita o patch XML do template (gerar_shopee_xlsx)
# ---------------------------------------------------------------------------

def exportar_shopee(catalogo: list, output_path: str, limite: int = 0):
    import gerar_shopee_xlsx as gs

    itens = catalogo[:limite] if limite else catalogo
    if not itens:
        print("[shopee] catálogo vazio — rode classificar_catalogo.py antes")
        return

    # adapta para o formato esperado pelo gerador, com PREÇO REAL por item
    produtos = [{
        "id": it["id"], "titulo": it["titulo"],
        "descricao": _descricao_rica(it),
        "preco": preco_plataforma(it["preco"], "shopee"),
        "ml_id": it["ml_id"], "imagem_path": it["imagem_path"],
    } for it in itens]

    gs.gerar_de_produtos(produtos, output_path)
    precos = sorted({p["preco"] for p in produtos})
    print(f"[shopee] {len(produtos)} produtos exportados -> {output_path}")
    print(f"[shopee] precos reais aplicados: {precos[:8]}{'...' if len(precos) > 8 else ''}")


def exportar_amazon(catalogo: list, output_path: str, limite: int = 0):
    raise NotImplementedError(
        "Amazon requer conta de vendedor + isenção de GTIN (apostila autoral não tem ISBN). "
        "Resolver Brand Registry/isenção de GTIN, então fornecer o flat-file da categoria. "
        "A camada de catálogo já está pronta: preco_plataforma('amazon') e os metadados meta_*."
    )


_PERFIS = {"shopee": exportar_shopee, "amazon": exportar_amazon}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plataforma", required=True, choices=list(_PERFIS))
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--output", default="")
    args = ap.parse_args()

    catalogo = carregar_catalogo()
    print(f"catálogo classificado: {len(catalogo)} anúncios")

    out = args.output or os.path.join(
        os.path.expanduser("~/Downloads"),
        f"{args.plataforma}_upload_{datetime.now():%Y-%m-%d}_{args.limite or len(catalogo)}.xlsx",
    )
    _PERFIS[args.plataforma](catalogo, out, limite=args.limite)


if __name__ == "__main__":
    main()
