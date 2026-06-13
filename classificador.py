"""classificador.py — classifica um anúncio (título + descrição do ML) em
metadados estruturados de catálogo, usados pelos exportadores multi-plataforma.

Para anúncios com vínculo no banco (kit_id/apostila_id) NÃO é preciso classificar
— a verdade é estrutural. Este módulo existe para os ÓRFÃOS (importados), cuja
única fonte de composição é o texto do anúncio. Reaproveita o pipeline Groq→Qwen
de generator.content (_chat_completions + _parse_json).

Saída (dict):
  tipo_oferta:    "individual" | "kit"
  conteudo:       "caca_palavras" | "cognitivo" | "misto"
  num_apostilas:  int   (quantas apostilas físicas o cliente recebe)
  num_exercicios: int   (total prometido; 0 se não informado)
  composicao:     str   (lista curta do que vem na caixa)
  confianca:      "alta" | "baixa"
"""

_SCHEMA_PADRAO = {
    "tipo_oferta": "individual",
    "conteudo": "cognitivo",
    "num_apostilas": 1,
    "num_exercicios": 0,
    "composicao": "",
    "confianca": "baixa",
}

_SYSTEM = (
    "Você classifica anúncios de apostilas físicas impressas para idosos. "
    "Responda SOMENTE com um objeto JSON, sem texto antes ou depois."
)

_PROMPT = """Classifique o anúncio abaixo e retorne EXATAMENTE este JSON:

{{
  "tipo_oferta": "individual" ou "kit",   // kit = cliente recebe 2+ apostilas
  "conteudo": "caca_palavras" ou "cognitivo" ou "misto",
  // caca_palavras = predominam caça-palavras/puzzles de letras
  // cognitivo = exercícios variados (memória, atenção, lógica, sem ser caça-palavras)
  // misto = kit que combina caça-palavras com outras apostilas cognitivas
  "num_apostilas": número inteiro de apostilas físicas que o comprador recebe,
  "num_exercicios": número total de exercícios/atividades prometido (0 se não disser),
  "composicao": "lista curta do que vem na caixa, separada por vírgula",
  "confianca": "alta" se o texto deixa claro, "baixa" se você teve que adivinhar
}}

TÍTULO: {titulo}

DESCRIÇÃO:
{descricao}
"""


def classificar(titulo: str, descricao: str = "") -> dict:
    """Classifica um anúncio. Nunca levanta exceção — retorna confiança 'baixa' em falha."""
    from generator.content import _chat_completions, _parse_json

    prompt = _PROMPT.format(
        titulo=(titulo or "").strip()[:300],
        descricao=(descricao or "").strip()[:2500] or "(sem descrição)",
    )
    try:
        raw = _chat_completions(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": prompt}],
            max_tokens=300,
        )
        data = _parse_json(raw)
        if not isinstance(data, dict):
            return dict(_SCHEMA_PADRAO)
    except Exception as e:
        print(f"[classificador] falha ({titulo[:40]!r}): {e}")
        return dict(_SCHEMA_PADRAO)

    # Normaliza e valida contra valores conhecidos
    out = dict(_SCHEMA_PADRAO)
    tipo = str(data.get("tipo_oferta", "")).lower()
    out["tipo_oferta"] = "kit" if "kit" in tipo else "individual"
    cont = str(data.get("conteudo", "")).lower()
    if "misto" in cont:
        out["conteudo"] = "misto"
    elif "caca" in cont or "caça" in cont or "palavra" in cont:
        out["conteudo"] = "caca_palavras"
    else:
        out["conteudo"] = "cognitivo"
    try:
        out["num_apostilas"] = max(1, int(data.get("num_apostilas") or 1))
    except (TypeError, ValueError):
        out["num_apostilas"] = 1
    try:
        out["num_exercicios"] = max(0, int(data.get("num_exercicios") or 0))
    except (TypeError, ValueError):
        out["num_exercicios"] = 0
    # coerência: kit tem 2+ apostilas
    if out["tipo_oferta"] == "kit" and out["num_apostilas"] < 2:
        out["num_apostilas"] = 2
    if out["num_apostilas"] >= 2:
        out["tipo_oferta"] = "kit"
    out["composicao"] = str(data.get("composicao") or "")[:200]
    out["confianca"] = "alta" if str(data.get("confianca", "")).lower() == "alta" else "baixa"
    return out
