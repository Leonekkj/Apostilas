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
import logging
import os
import re

from groq import Groq
from anthropic import Anthropic

FATIAS = [30, 60, 90, 120, 150, 200]
PRECOS_FATIA = {30: 14.90, 60: 19.90, 90: 24.90, 120: 29.90, 150: 34.90, 200: 44.90}

# ---------------------------------------------------------------------------
# Cliente (lazy-initialized so the module can be imported without a key)
# ---------------------------------------------------------------------------

def _client() -> Groq:
    return Groq(api_key=os.environ["GROQ_API_KEY"])


def _claude_client() -> Anthropic | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return Anthropic(api_key=api_key)


def _qwen_client():
    """Cliente OpenAI-compatible para Alibaba Cloud DashScope (Qwen)."""
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return None
    from openai import OpenAI as _OpenAI
    return _OpenAI(
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Constantes de modelo / tokens
# ---------------------------------------------------------------------------

_MODEL          = "llama-3.3-70b-versatile"  # Groq — modelo principal
_MODEL_FALLBACK = "llama-3.1-8b-instant"      # Groq — fallback quando quota do principal esgota
_QWEN_MODEL     = "qwen-turbo"                # Alibaba Cloud — fallback quando Groq esgota
_CLAUDE_MODEL   = "claude-sonnet-4-6"


def _chat_completions(msgs: list, max_tokens: int, json_mode: bool = True) -> str:
    """Tenta Groq (principal → fallback) e depois Qwen. Retorna o texto da resposta."""
    fmt = {"type": "json_object"} if json_mode else None
    groq = _client()

    for model in (_MODEL, _MODEL_FALLBACK):
        try:
            kw = dict(model=model, max_tokens=max_tokens, messages=msgs)
            if fmt:
                kw["response_format"] = fmt
            resp = groq.chat.completions.create(**kw)
            return resp.choices[0].message.content
        except Exception as exc:
            is_quota = "rate_limit" in str(exc).lower() or "429" in str(exc)
            if is_quota:
                logging.warning("[COGNIVITA] Quota esgotada para %s", model)
                continue
            raise

    # Groq esgotado — tenta Qwen
    qwen = _qwen_client()
    if qwen is not None:
        try:
            logging.info("[COGNIVITA] Usando Qwen (%s) como fallback", _QWEN_MODEL)
            kw = dict(model=_QWEN_MODEL, max_tokens=max_tokens, messages=msgs)
            if fmt:
                kw["response_format"] = fmt
            resp = qwen.chat.completions.create(**kw)
            return resp.choices[0].message.content
        except Exception as exc:
            logging.warning("[COGNIVITA] Qwen falhou: %s", exc)

    raise RuntimeError(
        "Quota diária do Groq esgotada e Qwen indisponível. "
        "Configure DASHSCOPE_API_KEY ou aguarde o reset do Groq (meia-noite UTC)."
    )

_SYSTEM_EDITORIAL = """\
Você é especialista em design editorial premium de materiais terapêuticos para idosos 60+.
Trabalha para a Cognivita (cognivita.com.br), marca premium de estimulação cognitiva.
Cria textos sofisticados, acolhedores e humanos — nunca robóticos, nunca infantilizantes.
Responda SEMPRE com JSON válido, sem texto extra antes ou depois do JSON.\
"""

_SYSTEM_GABARITO = """\
Você é revisor de exercícios cognitivos impressos para idosos 60+.
Analisa exercícios e retorna respostas corretas de forma clara e objetiva.
Responda SEMPRE com JSON válido, sem texto extra antes ou depois.\
"""

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
    """Remove possíveis marcadores markdown e faz o parse com múltiplas tentativas."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    # Tentativa 1: parse direto
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Tentativa 2: corrige sequências de escape inválidas (\N, \-, etc.)
    sanitized = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', text)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Tentativa 3: normaliza newlines literais + corrige ) usado como ] (bug comum do Groq).
    # Em JSON, ) nunca é caractere estrutural — substituir é sempre seguro.
    repaired = re.sub(r'\)(?=[,\]}"\':\s])', ']', sanitized)
    repaired = repaired.replace('\r\n', ' ').replace('\n', ' ')
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Tentativa 4: json_repair como último recurso
    try:
        from json_repair import repair_json
        fixed = repair_json(repaired)
        if fixed:
            return json.loads(fixed)
    except Exception:
        pass

    raise ValueError(
        f"Resposta do Claude não é JSON válido.\n"
        f"Texto recebido:\n{text[:500]}"
    )


# ---------------------------------------------------------------------------
# 1. gerar_conteudo
# ---------------------------------------------------------------------------

_BATCH_SIZE = 100  # Groq Llama 3.3 70B output limit ~8192 tokens; 100 exercises ≈ 7000 tokens


def _num_fases(num_exercicios: int) -> int:
    if num_exercicios <= 40:
        return 3
    elif num_exercicios <= 80:
        return 4
    return 5


def _stub_mapa_editorial(topico: dict, num_exercicios: int) -> dict:
    logging.warning(
        "[COGNIVITA] ANTHROPIC_API_KEY não definida — usando stub editorial. "
        "Defina a variável para ativar geração premium."
    )
    n_fases = _num_fases(num_exercicios)
    nomes = [
        "Ativação Leve",
        "Atenção e Foco",
        "Memória Viva",
        "Raciocínio Cotidiano",
        "Integração Cognitiva",
    ]
    secoes = ["MEMÓRIA", "ATENÇÃO", "RACIOCÍNIO", "LINGUAGEM", "PERCEPÇÃO"]
    por_fase = num_exercicios // n_fases
    sobra = num_exercicios % n_fases
    nome_topico = topico.get("nome", topico.get("name", str(topico)))

    fases = []
    for i in range(n_fases):
        n = por_fase + (1 if i < sobra else 0)
        fases.append({
            "numero": i + 1,
            "nome": nomes[i],
            "objetivo": f"Desenvolver habilidades cognitivas através de exercícios de {nomes[i].lower()}.",
            "abertura": (
                f"Bem-vindo à fase de {nomes[i]}. "
                f"Nesta etapa, você vai exercitar sua mente de forma leve e prazerosa. "
                f"Lembre-se: não há pressa. Cada exercício é uma pequena conquista."
            ),
            "secao": secoes[i % len(secoes)],
            "num_exercicios": n,
            "exercicios_numeros": [],
        })

    return {
        "apresentacao": (
            f"Bem-vindo à sua Apostila de {nome_topico}, da Coleção Bem Envelhecer da Cognivita.\n\n"
            f"Este material foi criado com carinho especialmente para você. "
            f"Cada exercício foi desenvolvido para estimular sua mente de forma gentil, "
            f"progressiva e prazerosa.\n\n"
            f"Dedique alguns minutos por dia a este material e sinta a diferença. "
            f"Seu cérebro agradece."
        ),
        "fases": fases,
        "rotina_semanal": {
            "texto": (
                "Sugerimos dedicar de 15 a 20 minutos por dia a esta apostila. "
                "Escolha um horário tranquilo, de preferência sempre o mesmo, "
                "para criar uma rotina agradável e consistente."
            ),
            "dias": [
                {"dia": "Segunda-feira",  "sugestao": "2 exercícios — período da manhã"},
                {"dia": "Terça-feira",    "sugestao": "2 exercícios — período da tarde"},
                {"dia": "Quarta-feira",   "sugestao": "Revisão leve ou descanso"},
                {"dia": "Quinta-feira",   "sugestao": "2 exercícios — período da manhã"},
                {"dia": "Sexta-feira",    "sugestao": "2 exercícios — período da tarde"},
                {"dia": "Sábado",         "sugestao": "1 exercício livre, sem pressão"},
                {"dia": "Domingo",        "sugestao": "Descanso merecido"},
            ],
        },
    }


def gerar_mapa_editorial(topico: dict, num_exercicios: int) -> dict:
    """
    Gera mapa editorial premium via Claude API.
    Retorna dict com apresentacao, fases[] e rotina_semanal.
    Usa stub se ANTHROPIC_API_KEY não estiver definida.
    """
    client = _claude_client()
    if client is None:
        return _stub_mapa_editorial(topico, num_exercicios)

    n_fases = _num_fases(num_exercicios)
    nome_topico = topico.get("nome", topico.get("name", str(topico)))
    descricao_topico = topico.get("descricao", topico.get("description", ""))
    por_fase = num_exercicios // n_fases
    sobra = num_exercicios % n_fases
    distribuicao = ", ".join(
        str(por_fase + (1 if i < sobra else 0)) for i in range(n_fases)
    )

    prompt = f"""\
Crie o mapa editorial para uma apostila Cognivita premium.

Tópico: {nome_topico}
Descrição: {descricao_topico}
Total de exercícios: {num_exercicios}
Número de fases: {n_fases}
Exercícios por fase (em ordem): {distribuicao}
Coleção: Bem Envelhecer

Retorne SOMENTE este JSON, sem texto antes ou depois:

{{
  "apresentacao": "Texto de boas-vindas em 2-3 parágrafos (300-500 palavras). Tom: sofisticado, acolhedor, humano. Fala sobre o tópico {nome_topico}, benefícios cognitivos, como usar. NUNCA infantilize o leitor idoso.",
  "fases": [
    {{
      "numero": 1,
      "nome": "Nome evocativo e elegante da fase",
      "objetivo": "Objetivo cognitivo específico desta fase, em 1 frase direta",
      "abertura": "Texto de abertura da fase (150-200 palavras). Motivador, acolhedor, conectado ao tópico {nome_topico}.",
      "secao": "UMA DE: MEMÓRIA / ATENÇÃO / RACIOCÍNIO / LINGUAGEM / PERCEPÇÃO",
      "num_exercicios": {por_fase},
      "exercicios_numeros": []
    }}
  ],
  "rotina_semanal": {{
    "texto": "Parágrafo de 80-100 palavras sobre a rotina sugerida. Leve, motivador.",
    "dias": [
      {{"dia": "Segunda-feira", "sugestao": "sugestão específica e leve"}},
      {{"dia": "Terça-feira",   "sugestao": "..."}},
      {{"dia": "Quarta-feira",  "sugestao": "..."}},
      {{"dia": "Quinta-feira",  "sugestao": "..."}},
      {{"dia": "Sexta-feira",   "sugestao": "..."}},
      {{"dia": "Sábado",        "sugestao": "..."}},
      {{"dia": "Domingo",       "sugestao": "..."}}
    ]
  }}
}}

Regras:
- Gere exatamente {n_fases} fases no array "fases"
- Variar as seções entre as fases (não repetir a mesma seção consecutivamente)
- Nomes de fase elegantes e únicos: ex "Ativação Leve", "Atenção Plena", "Memória Viva"
- num_exercicios de cada fase deve seguir exatamente a distribuição: {distribuicao}\
"""

    try:
        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt},
            ],
            system=_SYSTEM_EDITORIAL,
        )
        raw = response.content[0].text
        return _parse_json(raw)
    except Exception as exc:
        logging.warning("[COGNIVITA] Claude API error em gerar_mapa_editorial: %s — usando stub", exc)
        return _stub_mapa_editorial(topico, num_exercicios)


def gerar_gabarito(exercicios: list) -> list:
    """
    Gera gabarito para exercícios visuais (ligar, completar, sequencia) via Claude.
    Exercícios tipo texto e tabela são ignorados.
    Retorna lista vazia se não houver ANTHROPIC_API_KEY ou sem exercícios visuais.
    """
    visuais = [
        e for e in exercicios
        if e.get("tipo") in ("ligar", "completar", "sequencia")
        and e.get("dados_visuais")
    ]
    if not visuais:
        return []

    client = _claude_client()
    if client is None:
        return []

    exercicios_resumo = json.dumps(
        [
            {
                "exercicio": e["numero"],
                "titulo": e.get("titulo", ""),
                "tipo": e.get("tipo"),
                "dados_visuais": e.get("dados_visuais"),
            }
            for e in visuais
        ],
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""\
Analise os exercícios abaixo e retorne o gabarito de cada um.

Exercícios:
{exercicios_resumo}

Retorne SOMENTE este JSON:
[
  {{
    "exercicio": 3,
    "titulo": "Título do exercício",
    "resposta": "resposta formatada"
  }}
]

Formato da resposta por tipo:
- "ligar": "1-A, 2-C, 3-B" (número esquerda - letra direita, em ordem)
- "completar": liste as respostas das lacunas em ordem, separadas por " / "
- "sequencia": apenas o elemento que preenche o "???"

Retorne um objeto para cada exercício. Nenhum texto extra.\
"""

    try:
        response = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM_GABARITO,
        )
        raw = response.content[0].text
        result = _parse_json(raw)
        return result if isinstance(result, list) else []
    except Exception as exc:
        logging.warning("[COGNIVITA] Claude API error em gerar_gabarito: %s — retornando gabarito vazio", exc)
        return []


_TIPO_CICLO = ["texto", "ligar", "completar", "texto", "sequencia", "tabela"]

def _distribuir_tipos(n: int) -> list[str]:
    """Retorna sequência de tipos para n exercícios (~40% texto, 60% visual)."""
    return [_TIPO_CICLO[i % len(_TIPO_CICLO)] for i in range(n)]


_FORMATOS_TIPO = {
    "texto": """\
Tipo: TEXTO — exercício discursivo onde o idoso escreve a resposta nas linhas abaixo.
JSON de cada exercício:
{{"numero": N, "tipo": "texto", "titulo": "...", "descricao": "...", "instrucoes": ["..."], "espaco_resposta": "linha", "dados_visuais": null}}
espaco_resposta pode ser "linha" (linhas), "lista" (bullets) ou "quadrado" (caixa).""",

    "ligar": """\
Tipo: LIGAR — ligar coluna esquerda com coluna direita (3-5 pares).
JSON de cada exercício:
{{"numero": N, "tipo": "ligar", "titulo": "...", "descricao": "Ligue cada item ao seu par correto.", "instrucoes": ["Escreva o número ao lado de cada letra."], "espaco_resposta": "visual", "dados_visuais": {{"esquerda": ["item1","item2","item3"], "direita": ["par1","par2","par3"]}}}}
Os pares devem ser temáticos e relacionados ao tópico.""",

    "completar": """\
Tipo: COMPLETAR — preencher lacunas em frases com palavras da lista.
JSON de cada exercício:
{{"numero": N, "tipo": "completar", "titulo": "...", "descricao": "Complete as frases com as palavras da lista.", "instrucoes": ["Escreva a palavra correta no espaço ___"], "espaco_resposta": "visual", "dados_visuais": {{"frases": ["Frase com ___ lacuna."], "opcoes": ["certa","errada1","errada2","errada3"]}}}}
Inclua 2-3 frases e 4 opções (incluindo a correta). Use ___ para indicar a lacuna.""",

    "sequencia": """\
Tipo: SEQUÊNCIA — completar uma sequência lógica com o elemento que falta (???).
JSON de cada exercício:
{{"numero": N, "tipo": "sequencia", "titulo": "...", "descricao": "Qual elemento completa a sequência?", "instrucoes": ["Escreva sua resposta no espaço com ???"], "espaco_resposta": "visual", "dados_visuais": {{"items": ["elem1","elem2","???","elem4"]}}}}
Sequências podem ser: dias da semana, meses, números, estações, letras, padrões lógicos.""",

    "tabela": """\
Tipo: TABELA — preencher tabela com colunas definidas.
JSON de cada exercício:
{{"numero": N, "tipo": "tabela", "titulo": "...", "descricao": "Complete a tabela abaixo.", "instrucoes": ["Preencha cada célula com a informação solicitada."], "espaco_resposta": "visual", "dados_visuais": {{"colunas": ["Coluna1","Coluna2"], "linhas": 5}}}}
Use 2-3 colunas relevantes ao tópico e 4-5 linhas.""",
}


def _gerar_tipo_unico(topico: dict, tipo: str, n: int, fase: dict = None) -> list:
    """Gera n exercícios de UM único tipo. Numerados de 1 a n (remapeados depois)."""
    nome_topico = topico.get("nome", topico.get("name", str(topico)))
    descricao_topico = topico.get("descricao", topico.get("description", ""))
    formato = _FORMATOS_TIPO.get(tipo, _FORMATOS_TIPO["texto"])

    contexto_fase = ""
    if fase:
        contexto_fase = (
            f"\nFase: {fase.get('nome', '')} — {fase.get('objetivo', '')}\n"
        )

    prompt = f"""\
Gere exatamente {n} exercício(s) de estimulação cognitiva.
Tópico: {nome_topico} — {descricao_topico}{contexto_fase}

{formato}

Crie exercícios criativos e variados relacionados ao tópico "{nome_topico}".
Todos os exercícios devem ser adequados para idosos 60+, realizáveis em papel impresso.

Retorne SOMENTE este JSON com exatamente {n} exercício(s) no array:
{{"exercicios": [...]}}\
"""

    msgs = [
        {"role": "system", "content": _SYSTEM_CONTEUDO},
        {"role": "user", "content": prompt},
    ]
    raw = _chat_completions(msgs, max_tokens=4000)
    parsed = _parse_json(raw)
    return parsed.get("exercicios", [])


def _gerar_batch(topico: dict, n: int, offset: int = 0, fase: dict = None) -> list:
    """Gera n exercícios em UMA chamada Groq com distribuição de tipos garantida."""
    nome_topico = topico.get("nome", topico.get("name", str(topico)))
    inicio = offset + 1

    tipos_seq = _distribuir_tipos(n)
    lista_tipos = "\n".join(
        f'  {inicio + i}. tipo="{t}"' for i, t in enumerate(tipos_seq)
    )

    contexto_fase = ""
    if fase:
        contexto_fase = f"\nFase: {fase.get('nome', '')} — {fase.get('objetivo', '')}\n"

    prompt = f"""\
Gere exatamente {n} exercícios cognitivos para idosos 60+ sobre "{nome_topico}".{contexto_fase}
Numere de {inicio} a {inicio + n - 1}. Exercícios devem ser realizáveis em papel impresso.

TIPOS OBRIGATÓRIOS por exercício (siga esta ordem exata):
{lista_tipos}

FORMATOS por tipo:

"texto": {{"numero":N,"tipo":"texto","titulo":"...","descricao":"...","instrucoes":["..."],"espaco_resposta":"linha","dados_visuais":null}}

"ligar": {{"numero":N,"tipo":"ligar","titulo":"...","descricao":"Ligue cada item ao seu par.","instrucoes":["Escreva o número ao lado de cada letra."],"espaco_resposta":"visual","dados_visuais":{{"esquerda":["item1","item2","item3"],"direita":["par1","par2","par3"]}}}}
(3-5 pares temáticos de {nome_topico})

"completar": {{"numero":N,"tipo":"completar","titulo":"...","descricao":"Complete as frases.","instrucoes":["Escreva a palavra no espaço ___."],"espaco_resposta":"visual","dados_visuais":{{"frases":["Frase com ___ lacuna.","Outra ___ frase."],"opcoes":["certa","errada1","errada2","errada3"]}}}}
(2-3 frases, 4 opções)

"sequencia": {{"numero":N,"tipo":"sequencia","titulo":"...","descricao":"Complete a sequência.","instrucoes":["Escreva o que falta em ???."],"espaco_resposta":"visual","dados_visuais":{{"items":["a","b","???","d"]}}}}
(4-5 itens, ??? é a lacuna)

"tabela": {{"numero":N,"tipo":"tabela","titulo":"...","descricao":"Preencha a tabela.","instrucoes":["Preencha cada célula."],"espaco_resposta":"visual","dados_visuais":{{"colunas":["Col1","Col2","Col3"],"linhas":5}}}}
(2-3 colunas, 4-5 linhas)

Retorne SOMENTE: {{"exercicios": [todos os {n} exercícios]}}\
"""

    msgs = [
        {"role": "system", "content": _SYSTEM_CONTEUDO},
        {"role": "user", "content": prompt},
    ]
    raw = _chat_completions(msgs, max_tokens=8000)
    parsed = _parse_json(raw)
    exercicios = parsed.get("exercicios", [])
    for i, ex in enumerate(exercicios):
        if i < len(tipos_seq):
            ex["tipo"] = tipos_seq[i]
            ex["numero"] = inicio + i
    return exercicios


def gerar_conteudo(topico: dict, num_exercicios: int) -> str:
    """
    Gera conteúdo premium completo de uma apostila Cognivita.

    Fluxo:
      1. Claude gera mapa editorial (apresentacao, fases, rotina_semanal)
      2. Groq gera exercícios por fase com contexto da fase
      3. Claude gera gabarito dos exercícios visuais

    Returns:
        JSON string com schema enriquecido (fases, apresentacao, rotina_semanal, gabarito).
    """
    nome_topico = topico.get("nome", topico.get("name", str(topico)))

    # 1. Mapa editorial via Claude (ou stub)
    mapa = gerar_mapa_editorial(topico, num_exercicios)

    # 2. Exercícios por fase via Groq
    todos_exercicios: list = []
    offset = 0

    for fase in mapa["fases"]:
        n_fase = fase["num_exercicios"]
        fase_exercicios: list = []

        while len(fase_exercicios) < n_fase:
            n = min(_BATCH_SIZE, n_fase - len(fase_exercicios))
            batch = _gerar_batch(topico, n, offset + len(fase_exercicios), fase=fase)
            if not batch:
                logging.error("[COGNIVITA] _gerar_batch retornou vazio — interrompendo fase %s", fase.get('nome', ''))
                break
            fase_exercicios.extend(batch)

        fase["exercicios_numeros"] = [e["numero"] for e in fase_exercicios]
        todos_exercicios.extend(fase_exercicios)
        offset += n_fase

    # 3. Gabarito via Claude (ou vazio sem chave)
    gabarito = gerar_gabarito(todos_exercicios)

    result = {
        "topico": nome_topico,
        "num_exercicios": len(todos_exercicios),
        "colecao": "Bem Envelhecer",
        "apresentacao": mapa.get("apresentacao", ""),
        "fases": mapa["fases"],
        "rotina_semanal": mapa.get("rotina_semanal", {}),
        "exercicios": todos_exercicios,
        "gabarito": gabarito,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


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

    raw = _chat_completions([
        {"role": "system", "content": _SYSTEM_TITULOS},
        {"role": "user", "content": prompt},
    ], max_tokens=1024)
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

    return _chat_completions([
        {"role": "system", "content": _SYSTEM_TITULOS},
        {"role": "user", "content": prompt},
    ], max_tokens=600, json_mode=False).strip()


def gerar_descricao_digital_ml(topico: dict, num_exercicios: int) -> str:
    """Gera descrição para anúncio digital (PDF) no ML."""
    nome_topico = topico.get("nome", topico.get("name", str(topico)))

    prompt = f"""\
Crie uma descrição de produto para o Mercado Livre de uma apostila digital em PDF de estimulação cognitiva.

Produto: PDF de {nome_topico} com {num_exercicios} exercícios
Público: idosos 60+, cuidadores, terapeutas ocupacionais
Marca: CogniVita
Entrega: arquivo PDF enviado após confirmação do pagamento

Use EXATAMENTE este formato (mantenha os títulos em maiúscula, use • para bullets):

APOSTILA DIGITAL EM PDF — ESTIMULAÇÃO COGNITIVA PARA IDOSOS
[1 parágrafo de 2 frases descrevendo o produto digital e o tópico {nome_topico}]

Indicado para:
• [uso 1]
• [uso 2]
• [uso 3]
• [uso 4]

O QUE VOCÊ RECEBE
• PDF digital com {num_exercicios} exercícios de {nome_topico}
• Entrega imediata por mensagem após pagamento confirmado
• Arquivo pronto para imprimir em casa ou usar no tablet
• [outro benefício específico do formato digital]

BENEFÍCIOS
• [benefício 1 relacionado a {nome_topico}]
• [benefício 2]
• [benefício 3]
• Sem esperar entrega — acesso imediato ao material

EXEMPLOS DE ATIVIDADES
• [atividade 1 específica de {nome_topico}]
• [atividade 2]
• [atividade 3]
• [atividade 4]

ESPECIFICAÇÕES
• Formato: PDF Digital
• Quantidade: {num_exercicios} exercícios
• Tamanho das páginas: A4
• Impressão recomendada: Preto e Branco
• Fonte ampliada (ideal para idosos)

Retorne APENAS o texto acima preenchido, sem JSON, sem markdown, sem comentários.\
"""

    return _chat_completions([
        {"role": "system", "content": _SYSTEM_TITULOS},
        {"role": "user", "content": prompt},
    ], max_tokens=600, json_mode=False).strip()


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

    raw = _chat_completions([
        {"role": "system", "content": _SYSTEM_TITULOS},
        {"role": "user", "content": prompt},
    ], max_tokens=1024)
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

    nome = _chat_completions([
        {"role": "system", "content": "Você é especialista em naming de produtos para o público 60+. "
                                       "Responda apenas com o nome solicitado, sem explicações adicionais."},
        {"role": "user", "content": prompt},
    ], max_tokens=64, json_mode=False).strip().strip('"').strip("'").rstrip(".")
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

Formato obrigatório (máx 60 chars): "{nome_produto} {num_exercicios} Exercícios [complemento]"
Complemento deve mencionar idosos. Exemplos: "Para Idosos", "Apostila Física", "Estimulação Cognitiva".
Retorne SOMENTE o título final, sem aspas, sem chaves, sem JSON, sem explicação."""
    titulo = _chat_completions([
        {"role": "system", "content": "Você é especialista em títulos para Mercado Livre. Responda APENAS com o título solicitado, sem JSON, sem aspas, sem explicação."},
        {"role": "user", "content": prompt},
    ], max_tokens=80, json_mode=False).strip().strip('"').strip("'").rstrip(".")
    # Remove JSON artifacts if model still wraps the title
    if titulo.startswith("{") or titulo.startswith("["):
        try:
            parsed = _parse_json(titulo)
            if isinstance(parsed, dict):
                titulo = next(iter(parsed.values()), titulo)
            elif isinstance(parsed, list) and parsed:
                titulo = parsed[0].get("titulo", titulo) if isinstance(parsed[0], dict) else str(parsed[0])
        except Exception:
            titulo = titulo.lstrip("{[").split(":")[-1].strip().strip('"}]').strip()
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
