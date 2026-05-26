"""
generator/content.py
Cognivita — geração de conteúdo via Groq API (Llama 3.3 70B).

Funções:
  gerar_conteudo(topico, num_exercicios)       -> str (JSON)
  gerar_titulos_ml(topico, num_exercicios)     -> list[dict]
  gerar_titulos_kit_ml(kit_nome, apostilas, num_exercicios_total) -> list[dict]
  sugerir_nome_kit(apostilas)                  -> str
"""

import json
import os

from groq import Groq

FATIAS = [30, 60, 90, 120, 150, 200]
PRECOS_FATIA = {30: 14.90, 60: 19.90, 90: 24.90, 120: 29.90, 150: 34.90, 200: 44.90}

# ---------------------------------------------------------------------------
# Cliente (lazy-initialized so the module can be imported without a key)
# ---------------------------------------------------------------------------

def _client() -> Groq:
    return Groq(api_key=os.environ["GROQ_API_KEY"])


# ---------------------------------------------------------------------------
# Constantes de modelo / tokens
# ---------------------------------------------------------------------------

_MODEL = "llama-3.3-70b-versatile"   # Groq — gratuito, rápido, ótima qualidade

_SYSTEM_CONTEUDO = """\
Você é especialista em estimulação cognitiva para idosos. \
Cria exercícios físicos impressos (apostilas) para pessoas acima de 60 anos, \
seus cuidadores e terapeutas ocupacionais. \
O conteúdo deve ser simples, claro, acolhedor e adequado para impressão. \
Responda SEMPRE com JSON válido, sem texto extra antes ou depois do JSON. \
Nunca use markdown (sem ``` ou blocos de código).\
"""

_SYSTEM_TITULOS = """\
Você é especialista em copywriting para o Mercado Livre (ML). \
Cria títulos e descrições de produtos físicos impressos voltados para \
estimulação cognitiva de idosos 60+. \
Responda SEMPRE com JSON válido, sem texto extra antes ou depois do JSON.\
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json(text: str) -> object:
    """Remove possíveis marcadores markdown e faz o parse."""
    text = text.strip()
    # Remove blocos de código se Claude os incluir mesmo assim
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Resposta do Claude não é JSON válido.\n"
            f"Erro: {exc}\n"
            f"Texto recebido:\n{text[:500]}"
        ) from exc


# ---------------------------------------------------------------------------
# 1. gerar_conteudo
# ---------------------------------------------------------------------------

def gerar_conteudo(topico: dict, num_exercicios: int) -> str:
    """
    Gera conteúdo de exercícios para uma apostila física.

    Args:
        topico: dict com pelo menos {"nome": str, "descricao": str}
        num_exercicios: número de exercícios a gerar (ex: 60)

    Returns:
        JSON string com a estrutura de exercícios.
    """
    nome_topico = topico.get("nome", topico.get("name", str(topico)))
    descricao_topico = topico.get("descricao", topico.get("description", ""))

    prompt = f"""\
Gere exatamente {num_exercicios} exercícios de estimulação cognitiva para o tópico abaixo.

Tópico: {nome_topico}
Descrição: {descricao_topico}

Os exercícios devem:
- Ser adequados para idosos acima de 60 anos
- Usar linguagem simples e acessível
- Ser realizados em papel impresso (sem tecnologia)
- Ter espaço claro para o usuário responder

Retorne SOMENTE o seguinte JSON, sem nenhum texto antes ou depois:

{{
  "topico": "{nome_topico}",
  "num_exercicios": {num_exercicios},
  "exercicios": [
    {{
      "numero": 1,
      "titulo": "Título curto do exercício",
      "descricao": "Descrição clara e motivadora do exercício",
      "instrucoes": ["Passo 1", "Passo 2", "Passo 3"],
      "espaco_resposta": "linha"
    }}
  ]
}}

Valores válidos para espaco_resposta: "linha", "quadrado", "lista"
Gere todos os {num_exercicios} exercícios no array "exercicios".\
"""

    client = _client()
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=min(int(num_exercicios * 150) + 1000, 8000),  # Groq max ~8192
        messages=[
            {"role": "system", "content": _SYSTEM_CONTEUDO},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content
    # Valida que é JSON e devolve como string formatada
    parsed = _parse_json(raw)
    return json.dumps(parsed, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 2. gerar_titulos_ml
# ---------------------------------------------------------------------------

_ANGULOS = [
    ("beneficio",   "Foco no benefício cognitivo (memória, atenção, raciocínio, etc.)"),
    ("publico",     "Foco no público-alvo (idosos 60+, terceira idade, melhor idade)"),
    ("quantidade",  "Foco na quantidade de exercícios ou atividades do produto"),
    ("aplicacao",   "Foco no uso profissional (terapeuta ocupacional, fisioterapeuta, cuidador)"),
    ("resultado",   "Foco no resultado esperado (melhore a memória, estimule o cérebro)"),
    ("formato",     "Foco no formato físico do produto (impresso, encadernado, espiral, A4)"),
]


def gerar_titulos_ml(topico: dict, num_exercicios: int) -> list[dict]:
    """
    Gera 6 variações de títulos para anúncio no Mercado Livre.

    Args:
        topico: dict com {"nome": str, ...}
        num_exercicios: quantidade de exercícios da apostila

    Returns:
        Lista de 6 dicts: [{"variacao": int, "angulo": str, "titulo": str, "descricao": str}]
    """
    nome_topico = topico.get("nome", topico.get("name", str(topico)))

    angulos_texto = "\n".join(
        f'  {i+1}. angulo="{ang}" — {desc}'
        for i, (ang, desc) in enumerate(_ANGULOS)
    )

    prompt = f"""\
Crie 6 títulos otimizados para busca no Mercado Livre de uma apostila física impressa.

Produto: Apostila de {nome_topico} com {num_exercicios} exercícios
Público: idosos 60+, cuidadores, terapeutas ocupacionais

Regras obrigatórias:
- Máximo 60 caracteres por título (conte incluindo espaços)
- Title Case (primeira letra de cada palavra em maiúscula, exceto preposições curtas)
- Denso em palavras-chave que compradores digitam no ML
- Incluir "Para Idosos" em pelo menos 4 dos 6 títulos
- Variar os termos complementares entre os 6 (Apostila, Exercícios, Atividades, Cognitivo, Memória, Estimulação, Fonte Grande, A4, Impresso, Físico)
- Sem linguagem promocional (sem: Incrível, Melhor, Oferta, !, ?)
- Nenhum título pode ser idêntico a outro

Exemplos do formato desejado para um produto de Memória:
"Exercícios De Memória Para Idosos Apostila Física"
"Atividades Cognitivas Para Idosos Envelhecimento Saudável"
"Apostila Para Idosos Com Fonte Grande E Fácil Leitura"
"Estimulação Cognitiva Idosos 60 Exercícios Impressos"

Retorne SOMENTE este JSON, sem nenhum texto antes ou depois:

[
  {{"variacao": 1, "angulo": "beneficio",   "titulo": "...", "descricao": "Descrição de 3 a 4 frases para o corpo do anúncio ML."}},
  {{"variacao": 2, "angulo": "publico",     "titulo": "...", "descricao": "..."}},
  {{"variacao": 3, "angulo": "quantidade",  "titulo": "...", "descricao": "..."}},
  {{"variacao": 4, "angulo": "aplicacao",   "titulo": "...", "descricao": "..."}},
  {{"variacao": 5, "angulo": "resultado",   "titulo": "...", "descricao": "..."}},
  {{"variacao": 6, "angulo": "formato",     "titulo": "...", "descricao": "..."}}
]\
"""

    client = _client()
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": _SYSTEM_TITULOS},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content
    result = _parse_json(raw)

    if not isinstance(result, list) or len(result) != 6:
        raise ValueError(
            f"Esperava lista de 6 itens, recebi: {type(result).__name__} "
            f"com {len(result) if isinstance(result, list) else '?'} itens"
        )
    return result


# ---------------------------------------------------------------------------
# 3. gerar_descricao_ml
# ---------------------------------------------------------------------------

def gerar_descricao_ml(topico: dict, num_exercicios: int) -> str:
    """Gera descrição profissional para anúncio no ML no formato CogniVita."""
    nome_topico = topico.get("nome", topico.get("name", str(topico)))

    prompt = f"""\
Crie uma descrição de produto para o Mercado Livre de uma apostila física impressa de estimulação cognitiva.

Produto: Apostila de {nome_topico} com {num_exercicios} exercícios
Público: idosos 60+, cuidadores, terapeutas ocupacionais
Marca: CogniVita

Use EXATAMENTE este formato (mantenha os títulos em maiúscula, use • para bullets):

APOSTILA FÍSICA — ESTIMULAÇÃO COGNITIVA PARA IDOSOS
[1 parágrafo de 2 frases descrevendo o produto e o tópico {nome_topico}]

Indicado para:
• [uso 1]
• [uso 2]
• [uso 3]
• [uso 4]

O QUE VOCÊ RECEBE
• Apostila física impressa
• {num_exercicios} exercícios de {nome_topico}
• [outro item específico do produto]
• [outro item específico do produto]

BENEFÍCIOS
• [benefício 1 relacionado a {nome_topico}]
• [benefício 2]
• [benefício 3]
• [benefício 4]

EXEMPLOS DE ATIVIDADES
• [atividade 1 específica de {nome_topico}]
• [atividade 2]
• [atividade 3]
• [atividade 4]

ESPECIFICAÇÕES
• Tipo: Apostila Física Impressa
• Quantidade: {num_exercicios} atividades
• Tamanho: A4
• Impressão: Preto e Branco
• Fonte: Ampliada (ideal para idosos)

Retorne APENAS o texto acima preenchido, sem JSON, sem markdown, sem comentários.\
"""

    client = _client()
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=600,
        messages=[
            {"role": "system", "content": _SYSTEM_TITULOS},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# 4. gerar_titulos_kit_ml
# ---------------------------------------------------------------------------

def gerar_titulos_kit_ml(
    kit_nome: str,
    apostilas: list[dict],
    num_exercicios_total: int,
) -> list[dict]:
    """
    Gera 6 variações de títulos para um kit de apostilas no Mercado Livre.

    Args:
        kit_nome: nome do kit (ex: "Kit Memória + Atenção")
        apostilas: lista de dicts com {"nome": str} de cada apostila do kit
        num_exercicios_total: soma dos exercícios de todas as apostilas

    Returns:
        Lista de 6 dicts: [{"variacao": int, "angulo": str, "titulo": str, "descricao": str}]
    """
    nomes = ", ".join(a.get("nome", a.get("name", str(a))) for a in apostilas)
    qtd_apostilas = len(apostilas)

    angulos_kit = [
        ("combo",      "Foco no conjunto de apostilas (kit, combo, coleção)"),
        ("publico",    "Foco no público-alvo (idosos 60+, terceira idade, melhor idade)"),
        ("quantidade", f"Foco na quantidade ({num_exercicios_total} exercícios, {qtd_apostilas} apostilas)"),
        ("aplicacao",  "Foco no uso profissional (terapeuta ocupacional, cuidador, clínica)"),
        ("resultado",  "Foco no resultado (estimulação completa, saúde cognitiva)"),
        ("valor",      "Foco no custo-benefício do kit (economia, completo, tudo em um)"),
    ]

    angulos_texto = "\n".join(
        f'  {i+1}. angulo="{ang}" — {desc}'
        for i, (ang, desc) in enumerate(angulos_kit)
    )

    prompt = f"""\
Crie 6 títulos otimizados para busca no Mercado Livre de um kit de apostilas físicas impressas.

Kit: {kit_nome}
Apostilas incluídas: {nomes}
Total de exercícios: {num_exercicios_total}
Número de apostilas: {qtd_apostilas}
Público: idosos 60+, cuidadores, terapeutas ocupacionais

Regras obrigatórias:
- Máximo 60 caracteres por título
- Title Case
- Denso em palavras-chave de busca
- Incluir "Para Idosos" em pelo menos 4 dos 6 títulos
- Variar: Kit, Combo, Coleção, Apostilas, Exercícios, Cognitivo, Físico, Impresso, Estimulação
- Sem linguagem promocional (sem: Incrível, Melhor, Oferta, !, ?)
- Nenhum título idêntico a outro

Exemplos do formato desejado:
"Kit Apostilas Para Idosos Estimulação Cognitiva 120 Ex"
"Combo Atividades Cognitivas Para Idosos Físico Impresso"

Retorne SOMENTE este JSON, sem nenhum texto antes ou depois:

[
  {{"variacao": 1, "angulo": "combo",      "titulo": "...", "descricao": "3 a 4 frases para o corpo do anúncio."}},
  {{"variacao": 2, "angulo": "publico",    "titulo": "...", "descricao": "..."}},
  {{"variacao": 3, "angulo": "quantidade", "titulo": "...", "descricao": "..."}},
  {{"variacao": 4, "angulo": "aplicacao",  "titulo": "...", "descricao": "..."}},
  {{"variacao": 5, "angulo": "resultado",  "titulo": "...", "descricao": "..."}},
  {{"variacao": 6, "angulo": "valor",      "titulo": "...", "descricao": "..."}}
]\
"""

    client = _client()
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": _SYSTEM_TITULOS},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content
    result = _parse_json(raw)

    if not isinstance(result, list) or len(result) != 6:
        raise ValueError(
            f"Esperava lista de 6 itens, recebi: {type(result).__name__} "
            f"com {len(result) if isinstance(result, list) else '?'} itens"
        )
    return result


# ---------------------------------------------------------------------------
# 4. sugerir_nome_kit
# ---------------------------------------------------------------------------

def sugerir_nome_kit(apostilas: list[dict]) -> str:
    """
    Sugere um nome de kit com base nas apostilas incluídas.

    Args:
        apostilas: lista de dicts com {"nome": str}

    Returns:
        String com o nome sugerido, ex: "Kit Memória + Atenção"
    """
    nomes = ", ".join(a.get("nome", a.get("name", str(a))) for a in apostilas)

    prompt = f"""\
Sugira um nome comercial atraente para um kit de apostilas físicas de estimulação cognitiva.

Apostilas incluídas: {nomes}

Requisitos:
- Máximo 50 caracteres
- Começar com "Kit"
- Em português do Brasil
- Usar "+" entre os temas principais quando fizer sentido
- Soar acolhedor e profissional para idosos e familiares

Retorne SOMENTE o nome, sem aspas, sem ponto final, sem explicação.\
"""

    client = _client()
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=64,
        messages=[
            {"role": "system", "content": "Você é especialista em naming de produtos para o público 60+. "
                                           "Responda apenas com o nome solicitado, sem explicações adicionais."},
            {"role": "user", "content": prompt},
        ],
    )

    nome = response.choices[0].message.content.strip().strip('"').strip("'").rstrip(".")
    return nome


# ---------------------------------------------------------------------------
# 5. fatiar_conteudo
# ---------------------------------------------------------------------------

def fatiar_conteudo(conteudo_json: str, n: int) -> str:
    """Retorna JSON com os primeiros N exercícios do conteúdo completo."""
    data = json.loads(conteudo_json)
    data["exercicios"] = data.get("exercicios", [])[:n]
    data["num_exercicios"] = len(data["exercicios"])
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 6. gerar_titulo_apostila_produto
# ---------------------------------------------------------------------------

def gerar_titulo_apostila_produto(nome_produto: str, num_exercicios: int) -> str:
    """Gera 1 título ML otimizado para uma apostila dentro de uma linha de produto."""
    prompt = f"""\
Crie 1 título otimizado para Mercado Livre de apostila física impressa.
Linha: {nome_produto} | Exercícios: {num_exercicios} | Público: idosos 60+

Formato obrigatório (máx 60 chars): "{nome_produto} — {num_exercicios} Exercícios | [complemento]"
Complemento deve mencionar idosos. Varie: Apostila Física, Estimulação Cognitiva, etc.
Retorne SOMENTE o título, sem aspas, sem explicação."""
    client = _client()
    response = client.chat.completions.create(
        model=_MODEL,
        max_tokens=80,
        messages=[
            {"role": "system", "content": _SYSTEM_TITULOS},
            {"role": "user", "content": prompt},
        ],
    )
    titulo = response.choices[0].message.content.strip().strip('"').rstrip(".")
    return titulo[:60] if len(titulo) > 60 else titulo


# ---------------------------------------------------------------------------
# Bloco __main__ — teste de importação / uso exemplo (sem chamada de API)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("generator.content — módulo de geração de conteúdo Cognivita")
    print("=" * 60)
    print()
    print("Funções disponíveis:")
    print("  gerar_conteudo(topico, num_exercicios) -> str (JSON)")
    print("  gerar_titulos_ml(topico, num_exercicios) -> list[dict]")
    print("  gerar_titulos_kit_ml(kit_nome, apostilas, num_exercicios_total) -> list[dict]")
    print("  sugerir_nome_kit(apostilas) -> str")
    print()
    print("Modelo usado:", _MODEL)
    print()
    print("Exemplo de uso:")
    print()
    print('  from generator.content import gerar_conteudo, gerar_titulos_ml')
    print()
    print('  topico = {"nome": "Memória", "descricao": "Exercícios de memória de curto e longo prazo"}')
    print()
    print('  # Gerar conteúdo (requer GROQ_API_KEY)')
    print('  conteudo_json = gerar_conteudo(topico, num_exercicios=60)')
    print()
    print('  # Gerar títulos ML (requer GROQ_API_KEY)')
    print('  titulos = gerar_titulos_ml(topico, num_exercicios=60)')
    print()
    print("Estrutura esperada de gerar_conteudo:")
    exemplo_conteudo = {
        "topico": "Memória",
        "num_exercicios": 60,
        "exercicios": [
            {
                "numero": 1,
                "titulo": "Exemplo de Exercício",
                "descricao": "Descrição clara do exercício para idosos.",
                "instrucoes": ["Passo 1", "Passo 2"],
                "espaco_resposta": "linha",
            }
        ],
    }
    print(json.dumps(exemplo_conteudo, ensure_ascii=False, indent=2))
    print()
    print("Estrutura esperada de gerar_titulos_ml:")
    exemplo_titulos = [
        {"variacao": 1, "angulo": "beneficio", "titulo": "Apostila de Memória para Idosos 60+", "descricao": "..."},
        {"variacao": 2, "angulo": "publico",    "titulo": "Atividades de Memória Terceira Idade", "descricao": "..."},
        {"variacao": 3, "angulo": "quantidade", "titulo": "60 Exercícios de Memória Impressos",   "descricao": "..."},
        {"variacao": 4, "angulo": "aplicacao",  "titulo": "Apostila Memória Terapeuta Ocupacional", "descricao": "..."},
        {"variacao": 5, "angulo": "resultado",  "titulo": "Melhore a Memória com Exercícios Impressos", "descricao": "..."},
        {"variacao": 6, "angulo": "formato",    "titulo": "Apostila Impressa Memória Idosos A4", "descricao": "..."},
    ]
    print(json.dumps(exemplo_titulos, ensure_ascii=False, indent=2))
    print()
    print("Importação OK.")
