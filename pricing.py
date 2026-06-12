"""pricing.py — fonte única de preços e regras de precificação.

Importado por api.py, scheduler.py, database.py, ml/client.py e validacao.py.
NÃO importa nada do projeto (sem risco de import circular).
"""

FATIAS = [30, 60, 90, 120, 150, 200]

# Preços físicos reais (verificados nos anúncios publicados no ML)
PRECOS_PRODUTO = {30: 59.99, 60: 69.99, 90: 79.99, 120: 89.99, 150: 99.99, 200: 139.99}

# Preços digitais
PRECOS_DIGITAL = {30: 16.00, 60: 24.00, 90: 32.00, 120: 40.00, 150: 48.00, 200: 56.00}

# Caça-palavras FÍSICO por dificuldade (tabela digital antiga 14,90–34,90 REVOGADA).
# Base: 60 puzzles = 38 págs ≈ R$16 impressão + R$22 frete + 17% ML → piso ~R$48.
# Gigante (300 puzzles ≈ 158 págs) custa ~R$90 de produção+frete.
PRECOS_CACA_PALAVRAS = {
    "facil":   59.99,
    "medio":   64.99,
    "dificil": 69.99,
    "gigante": 139.99,
}

# Kit = soma dos preços individuais × desconto
DESCONTO_KIT = 0.85

# Preço usado como "real" de um anúncio individual ao montar kits
PRECO_MINIMO_FISICO_REAL = 50.0
PRECO_FALLBACK_INDIVIDUAL = 79.99

# Faixas (min, max) aceitáveis por tipo de anúncio — usadas pela validação.
# "importado" reflete anúncios reais do ML: nunca auto-corrigir, só reportar.
FAIXAS = {
    "fisico":    (50.0, 400.0),
    "digital":   (10.0, 100.0),
    "importado": (10.0, 500.0),
}


def preco_canonico(tipo: str, num_exercicios=None, dificuldade: str = None):
    """Preço de tabela para um anúncio individual (não-kit).

    Retorna None quando não há preço mapeável (ex: fatia desconhecida).
    """
    if dificuldade:
        return PRECOS_CACA_PALAVRAS.get(str(dificuldade).lower())
    tabela = PRECOS_DIGITAL if tipo == "digital" else PRECOS_PRODUTO
    try:
        return tabela.get(int(num_exercicios)) if num_exercicios else None
    except (TypeError, ValueError):
        return None


def preco_kit(soma_individuais: float) -> float:
    """Preço de kit: soma dos individuais com desconto, 2 casas."""
    return round(float(soma_individuais) * DESCONTO_KIT, 2)


def preco_na_faixa(tipo: str, preco: float) -> bool:
    """True se o preço está dentro da faixa aceitável do tipo (kit usa faixa do físico)."""
    minimo, maximo = FAIXAS.get(tipo, FAIXAS["fisico"])
    try:
        return minimo <= float(preco) <= maximo
    except (TypeError, ValueError):
        return False
