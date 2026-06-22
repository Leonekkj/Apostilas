import financeiro


def _venda(valor, qtd=1, comissao=0.0, frete=0.0, chave="p1", nome="Apostila A"):
    return {"valor": valor, "quantidade": qtd, "comissao_ml": comissao,
            "frete_custo": frete, "produto_chave": chave, "produto_nome": nome}


def test_margem_venda_desconta_tarifas():
    v = _venda(100.0, qtd=2, comissao=20.0, frete=10.0)  # receita 200
    assert financeiro.margem_venda(v) == 170.0


def test_resumo_periodo_soma_e_lucro():
    vendas = [_venda(100.0, comissao=17.0, frete=20.0),
              _venda(50.0, comissao=8.0, frete=20.0)]
    despesas = [{"categoria": "grafica", "valor": 30.0},
                {"categoria": "ads", "valor": 25.0}]
    r = financeiro.resumo_periodo(vendas, despesas)
    assert r["faturamento"] == 150.0
    assert r["comissao"] == 25.0
    assert r["frete"] == 40.0
    assert r["grafica"] == 30.0
    assert r["ads"] == 25.0
    # margem total = 150 - 25 - 40 = 85 ; lucro = 85 - 30 - 25 = 30
    assert r["lucro_liquido"] == 30.0
    assert round(r["margem_pct"], 2) == 20.0


def test_resumo_periodo_vazio_nao_divide_por_zero():
    r = financeiro.resumo_periodo([], [])
    assert r["faturamento"] == 0.0
    assert r["lucro_liquido"] == 0.0
    assert r["margem_pct"] == 0.0


def test_por_produto_rateia_despesas_por_faturamento():
    vendas = [_venda(150.0, comissao=15.0, frete=0.0, chave="a", nome="A"),
              _venda(50.0, comissao=5.0, frete=0.0, chave="b", nome="B")]
    despesas = [{"categoria": "grafica", "valor": 40.0}]  # total faturamento 200
    linhas = {l["produto_chave"]: l for l in financeiro.por_produto(vendas, despesas)}
    a, b = linhas["a"], linhas["b"]
    assert a["margem_contribuicao"] == 135.0
    assert b["margem_contribuicao"] == 45.0
    # rateio: A = 40 * (150/200) = 30 ; B = 40 * (50/200) = 10
    assert a["rateio"] == 30.0
    assert b["rateio"] == 10.0
    assert a["lucro_liquido_estimado"] == 105.0
    assert b["lucro_liquido_estimado"] == 35.0
