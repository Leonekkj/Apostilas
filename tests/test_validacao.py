"""Testes das regras puras de pricing.py e validacao.py (sem rede, sem banco)."""

import pricing
import validacao
from validacao import dedupe_titulos, fit_titulo, validar_anuncio


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------

def test_preco_kit_aplica_desconto_e_arredonda():
    assert pricing.preco_kit(100) == 85.0
    assert pricing.preco_kit(139.99 + 99.99) == round((139.99 + 99.99) * 0.85, 2)


def test_preco_canonico_fisico_digital_e_cp():
    assert pricing.preco_canonico("fisico", 60) == 69.99
    assert pricing.preco_canonico("digital", 90) == 32.00
    assert pricing.preco_canonico("fisico", None, dificuldade="gigante") == 139.99
    assert pricing.preco_canonico("fisico", None, dificuldade="facil") == 59.99
    assert pricing.preco_canonico("fisico", 999) is None
    assert pricing.preco_canonico("fisico", None) is None


def test_preco_na_faixa():
    assert pricing.preco_na_faixa("fisico", 69.99)
    assert not pricing.preco_na_faixa("fisico", 45.0)
    assert pricing.preco_na_faixa("digital", 16.0)
    assert not pricing.preco_na_faixa("digital", 5.0)
    assert not pricing.preco_na_faixa("fisico", None)


# ---------------------------------------------------------------------------
# fit_titulo
# ---------------------------------------------------------------------------

def test_fit_titulo_curto_inalterado():
    assert fit_titulo("Apostila Memória 60 Exercícios") == "Apostila Memória 60 Exercícios"


def test_fit_titulo_corta_na_palavra():
    titulo = "Apostila Estimulação Cognitiva Para Idosos Com Exercícios Variados Premium"
    resultado = fit_titulo(titulo)
    assert len(resultado) <= 60
    assert not resultado.endswith(" ")
    # não corta no meio de palavra: o resultado é prefixo terminado em palavra completa
    assert titulo.startswith(resultado)


def test_fit_titulo_preserva_pdf():
    titulo = "Caça-Palavras Nível Difícil Para Idosos Estimulação PDF Digital Premium"
    resultado = fit_titulo(titulo)
    assert len(resultado) <= 60
    assert "PDF" in resultado


# ---------------------------------------------------------------------------
# dedupe_titulos
# ---------------------------------------------------------------------------

def test_dedupe_titulos_seis_iguais_viram_unicos():
    titulos = [{"variacao": i, "titulo": "Kit Apostilas Cognitivas Para Idosos"} for i in range(1, 7)]
    resultado = dedupe_titulos(titulos)
    valores = [t["titulo"].lower() for t in resultado]
    assert len(set(valores)) == 6
    assert all(len(t["titulo"]) <= 60 for t in resultado)


def test_dedupe_titulos_trunca_longos():
    longo = "Kit Completo Apostilas Estimulação Cognitiva Memória Atenção Para Idosos 360 Exercícios"
    titulos = [{"titulo": longo}, {"titulo": "Outro Título"}]
    resultado = dedupe_titulos(titulos)
    assert len(resultado[0]["titulo"]) <= 60
    assert resultado[1]["titulo"] == "Outro Título"


def test_dedupe_titulos_case_insensitive():
    titulos = [{"titulo": "Apostila Memória"}, {"titulo": "APOSTILA MEMÓRIA"}]
    resultado = dedupe_titulos(titulos)
    assert resultado[0]["titulo"].lower() != resultado[1]["titulo"].lower()


# ---------------------------------------------------------------------------
# validar_anuncio
# ---------------------------------------------------------------------------

def _anuncio(**kw):
    base = {"id": 99, "titulo": "Apostila Memória 60 Exercícios", "preco": 69.99,
            "tipo": "fisico", "kit_id": None, "apostila_id": 1, "num_exercicios": 60,
            "imagem_path": "output/images/x.png"}
    base.update(kw)
    return base


def test_valido_passa_sem_correcoes():
    correcoes, corrigidos, bloqueios = validar_anuncio(_anuncio())
    assert correcoes == {} and corrigidos == [] and bloqueios == []


def test_preco_zero_bloqueia():
    _, _, bloqueios = validar_anuncio(_anuncio(preco=0))
    assert any("preço" in b for b in bloqueios)


def test_preco_negativo_bloqueia():
    _, _, bloqueios = validar_anuncio(_anuncio(preco=-5))
    assert any("preço" in b for b in bloqueios)


def test_titulo_vazio_bloqueia():
    _, _, bloqueios = validar_anuncio(_anuncio(titulo="   "))
    assert any("título" in b for b in bloqueios)


def test_titulo_longo_corrigido():
    longo = "Apostila Estimulação Cognitiva Para Idosos Com Muitos Exercícios Variados"
    correcoes, corrigidos, bloqueios = validar_anuncio(_anuncio(titulo=longo))
    assert bloqueios == []
    assert len(correcoes["titulo"]) <= 60


def test_preco_fisico_fora_da_faixa_corrige_para_canonico():
    correcoes, corrigidos, bloqueios = validar_anuncio(_anuncio(preco=45.0, num_exercicios=60))
    assert bloqueios == []
    assert correcoes["preco"] == 69.99


def test_preco_fora_da_faixa_sem_canonico_bloqueia():
    _, _, bloqueios = validar_anuncio(_anuncio(preco=45.0, num_exercicios=None))
    assert any("faixa" in b for b in bloqueios)


def test_kit_nao_valida_faixa():
    # kit de 4 apostilas pode passar de 400 — não aplica faixa
    correcoes, _, bloqueios = validar_anuncio(_anuncio(kit_id=7, apostila_id=None, preco=476.0))
    assert bloqueios == [] and "preco" not in correcoes


def test_importado_nunca_corrigido():
    correcoes, _, bloqueios = validar_anuncio(_anuncio(tipo="importado", preco=7.0))
    assert bloqueios == [] and "preco" not in correcoes


def test_publicacao_sem_imagem_e_sem_fonte_bloqueia():
    _, _, bloqueios = validar_anuncio(
        _anuncio(imagem_path="", apostila_id=None, kit_id=None), contexto="publicacao"
    )
    assert any("imagem" in b for b in bloqueios)


def test_publicacao_sem_imagem_com_apostila_nao_bloqueia():
    # tem apostila_id → publicar_anuncio gera capa on-demand
    _, _, bloqueios = validar_anuncio(_anuncio(imagem_path=""), contexto="publicacao")
    assert bloqueios == []


def test_criacao_titulo_duplicado_vira_vol_n(monkeypatch):
    import database
    existentes = {"apostila memória 60 exercícios"}
    monkeypatch.setattr(
        database, "existe_titulo",
        lambda titulo, excluir_id=None, incluir_rascunhos=True: titulo.lower() in existentes,
    )
    correcoes, corrigidos, bloqueios = validar_anuncio(_anuncio(), contexto="criacao")
    assert bloqueios == []
    assert correcoes["titulo"].endswith("Vol. 2")
    assert len(correcoes["titulo"]) <= 60
