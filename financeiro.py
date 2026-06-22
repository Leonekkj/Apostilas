"""financeiro.py — cálculo puro de margem, lucro e rateio.

Sem import de banco nem de rede (testável isoladamente). Recebe listas de
dicts já filtradas por período.
"""


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def margem_venda(venda: dict) -> float:
    """Margem de contribuição de uma venda = receita - comissão - frete."""
    receita = _f(venda.get("valor")) * _f(venda.get("quantidade") or 1)
    return round(receita - _f(venda.get("comissao_ml")) - _f(venda.get("frete_custo")), 2)


def _receita(venda: dict) -> float:
    return _f(venda.get("valor")) * _f(venda.get("quantidade") or 1)


def resumo_periodo(vendas: list[dict], despesas: list[dict]) -> dict:
    faturamento = round(sum(_receita(v) for v in vendas), 2)
    comissao = round(sum(_f(v.get("comissao_ml")) for v in vendas), 2)
    frete = round(sum(_f(v.get("frete_custo")) for v in vendas), 2)
    grafica = round(sum(_f(d.get("valor")) for d in despesas if d.get("categoria") == "grafica"), 2)
    ads = round(sum(_f(d.get("valor")) for d in despesas if d.get("categoria") == "ads"), 2)
    outras = round(sum(_f(d.get("valor")) for d in despesas
                       if d.get("categoria") not in ("grafica", "ads")), 2)
    margem_total = sum(margem_venda(v) for v in vendas)
    lucro = round(margem_total - grafica - ads - outras, 2)
    margem_pct = round((lucro / faturamento * 100), 2) if faturamento else 0.0
    return {
        "faturamento": faturamento,
        "comissao": comissao,
        "frete": frete,
        "grafica": grafica,
        "ads": ads,
        "outras_despesas": outras,
        "lucro_liquido": lucro,
        "margem_pct": margem_pct,
    }


def por_produto(vendas: list[dict], despesas: list[dict]) -> list[dict]:
    despesas_periodo = round(sum(_f(d.get("valor")) for d in despesas), 2)
    faturamento_total = sum(_receita(v) for v in vendas)

    agrupado: dict = {}
    for v in vendas:
        chave = v.get("produto_chave")
        item = agrupado.setdefault(chave, {
            "produto_chave": chave,
            "produto_nome": v.get("produto_nome") or "Sem produto",
            "faturamento": 0.0,
            "tarifas": 0.0,
            "margem_contribuicao": 0.0,
        })
        item["faturamento"] += _receita(v)
        item["tarifas"] += _f(v.get("comissao_ml")) + _f(v.get("frete_custo"))
        item["margem_contribuicao"] += margem_venda(v)

    linhas = []
    for item in agrupado.values():
        rateio = (despesas_periodo * (item["faturamento"] / faturamento_total)
                  if faturamento_total else 0.0)
        item["faturamento"] = round(item["faturamento"], 2)
        item["tarifas"] = round(item["tarifas"], 2)
        item["margem_contribuicao"] = round(item["margem_contribuicao"], 2)
        item["rateio"] = round(rateio, 2)
        item["lucro_liquido_estimado"] = round(item["margem_contribuicao"] - rateio, 2)
        linhas.append(item)

    linhas.sort(key=lambda x: x["lucro_liquido_estimado"], reverse=True)
    return linhas
