"""
generator/html_render.py
Converte conteúdo de apostila para HTML pronto para impressão via Playwright.
"""

import json
import html as _html_escape

from generator import _pdf_assets

COLOR_DARK = "#0C3322"
COLOR_GREEN = "#1B6B4A"
COLOR_BG = "#F7F3EC"
COLOR_TEXT = "#1A2820"
COLOR_MUTED = "#6B7E76"
COLOR_BORDER = "#E0E8E4"
COLOR_LIGHT_GREEN = "#D4EDE3"


def _css() -> str:
    return _pdf_assets.PREMIUM_CSS


def _apresentacao_html(texto: str) -> str:
    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    if not paragrafos:
        paragrafos = [texto.strip()]
    paras_html = "".join(
        f'<p>{_html_escape.escape(p)}</p>' for p in paragrafos
    )
    return f"""
<div class="page">
  <div class="instructions-header">APRESENTAÇÃO</div>
  <div class="apresentacao-body">{paras_html}</div>
</div>
"""


def _indice_html(fases: list) -> str:
    items = ""
    for fase in fases:
        nome = _html_escape.escape(f"Fase {fase['numero']} — {fase['nome']}")
        secao = _html_escape.escape(fase.get("secao", ""))
        items += f"""
<div class="indice-item">
  <span class="indice-fase-nome">{nome}</span>
  <span class="indice-secao">{secao}</span>
</div>"""
    return f"""
<div class="page">
  <div class="instructions-header">ÍNDICE</div>
  <div class="indice">{items}</div>
</div>
"""


def _fase_abertura_html(fase: dict) -> str:
    numero = fase.get("numero", "")
    nome = _html_escape.escape(str(fase.get("nome", "")))
    secao = _html_escape.escape(str(fase.get("secao", "")))
    objetivo = _html_escape.escape(str(fase.get("objetivo", "")))
    abertura = str(fase.get("abertura", ""))
    paragrafos = [p.strip() for p in abertura.split("\n\n") if p.strip()]
    if not paragrafos:
        paragrafos = [abertura.strip()]
    abertura_html = "".join(
        f'<p>{_html_escape.escape(p)}</p>' for p in paragrafos
    )
    return f"""
<div class="page fase-abertura">
  <div class="fase-bar">
    <span class="fase-num">FASE {numero}</span>
    <span class="fase-nome">{nome}</span>
  </div>
  <div class="fase-secao-tag">{secao}</div>
  <p class="fase-objetivo">{objetivo}</p>
  <div class="fase-abertura-text">{abertura_html}</div>
</div>
"""


def _rotina_semanal_html(rotina: dict) -> str:
    texto = _html_escape.escape(str(rotina.get("texto", "")))
    dias = rotina.get("dias", [])
    rows = ""
    for d in dias:
        dia = _html_escape.escape(str(d.get("dia", "")))
        sugestao = _html_escape.escape(str(d.get("sugestao", "")))
        rows += f"""
<tr>
  <td class="rotina-dia">{dia}</td>
  <td class="rotina-sugestao">{sugestao}</td>
  <td class="rotina-check"><span class="rotina-checkbox"></span></td>
</tr>"""
    return f"""
<div class="page">
  <div class="instructions-header">ROTINA SEMANAL</div>
  <p class="rotina-texto">{texto}</p>
  <table class="rotina-table">
    <thead>
      <tr>
        <th>Dia</th>
        <th>Sugestão de Atividade</th>
        <th>✓</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
"""


def _gabarito_html(gabarito: list) -> str:
    if not gabarito:
        return ""
    items = ""
    for g in gabarito:
        num = g.get("exercicio", "")
        titulo = _html_escape.escape(str(g.get("titulo", "")))
        resposta = _html_escape.escape(str(g.get("resposta", "")))
        items += f"""
<div class="gabarito-item">
  <span class="gabarito-num">Exercício {num}</span>
  <span class="gabarito-titulo">{titulo}</span>
  <span class="gabarito-resposta">{resposta}</span>
</div>"""
    return f"""
<div class="page">
  <div class="instructions-header">GABARITO</div>
  <div class="gabarito-grid">{items}</div>
</div>
"""


def _contracapa_html() -> str:
    return """
<div class="page bleed contracapa">
  <div class="contracapa-logo">Cognivita</div>
  <hr class="contracapa-rule">
  <div class="contracapa-tagline">Coleção Bem Envelhecer</div>
  <div class="contracapa-domain">cognivita.com.br</div>
</div>
"""


def _cover_html(topico: dict, num_exercicios: int, capa_img=None) -> str:
    nome = _html_escape.escape(topico.get("nome", topico.get("name", "")))

    # Arte do livro: a mesma capa que aparece nas fotos dos anúncios,
    # ocupando a área útil da página (a arte já traz marca e título)
    if capa_img:
        from generator.cp_html_render import file_data_uri
        foto = file_data_uri(capa_img)
        if foto:
            return f"""
<div class="page cover">
  <img src="{foto}" alt=""
       style="display:block; width:170mm; height:250mm; object-fit:cover; margin:0 auto;">
</div>
"""

    return f"""
<div class="page cover">
  <div class="cover-brand-bar">Estimulação Cognitiva para Idosos</div>
  <div class="cover-logo">Cognivita</div>
  <hr class="cover-rule">
  <div class="cover-tagline">Material Impresso · Coleção Bem Envelhecer</div>
  <div class="cover-title">Apostila de {nome}</div>
  <div class="cover-subtitle">Para Idosos 60+ &nbsp;·&nbsp; {num_exercicios} Exercícios</div>
  <div class="cover-footer-bar">Material Físico &nbsp;|&nbsp; Impresso e Encadernado</div>
  <div class="cover-domain">cognivita.com.br</div>
</div>
"""


def _instructions_html(nome_topico: str, num_exercicios: int) -> str:
    nome = _html_escape.escape(nome_topico)
    dicas = [
        "Faça os exercícios no seu próprio ritmo — não há pressa.",
        "Use caneta ou lápis com ponta grossa para escrever com mais conforto.",
        "Se precisar de ajuda, peça a um familiar ou cuidador.",
        "Tente fazer pelo menos 2 exercícios por dia para manter a rotina.",
        "Não existe resposta errada — o importante é exercitar o cérebro.",
        "Parabéns por cuidar da sua saúde cognitiva!",
    ]
    dicas_html = "".join(
        f'<div class="instructions-tip">• {_html_escape.escape(d)}</div>' for d in dicas
    )
    return f"""
<div class="page">
  <div class="instructions-header">COMO USAR ESTA APOSTILA</div>
  <p class="instructions-body">
    Esta apostila contém <strong>{num_exercicios} exercícios</strong> de estimulação cognitiva
    para o tema <strong>{nome}</strong>, desenvolvidos especialmente para pessoas acima de 60 anos.
  </p>
  <div class="instructions-tips-title">Dicas para aproveitar melhor:</div>
  {dicas_html}
  <hr class="instructions-rule">
  <p class="instructions-footer">
    Este material foi produzido pela equipe Cognivita com base em técnicas de
    estimulação cognitiva recomendadas por terapeutas ocupacionais e especialistas
    em saúde do idoso.
  </p>
</div>
"""


def _answer_space_html(espaco: str) -> str:
    if espaco == "quadrado":
        return '<div class="answer-label">Sua resposta:</div><div class="answer-box"></div>'
    if espaco == "lista":
        items = "".join(
            '<li>• &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</li>'
            for _ in range(5)
        )
        return f'<div class="answer-label">Sua resposta:</div><ul class="answer-bullets">{items}</ul>'
    lines = "".join('<div class="answer-line"></div>' for _ in range(5))
    return f'<div class="answer-label">Sua resposta:</div>{lines}'


def _exercise_ligar_html(dados: dict) -> str:
    esquerda = dados.get("esquerda", [])
    direita = dados.get("direita", [])
    left_items = "".join(
        f'<div class="match-item"><span class="match-item-num">{i + 1}.</span> '
        f'{_html_escape.escape(str(item))} <span class="match-answer-blank">&nbsp;</span></div>'
        for i, item in enumerate(esquerda)
    )
    right_items = "".join(
        f'<div class="match-item"><span class="match-item-letter">{chr(65 + i)}.</span> '
        f'{_html_escape.escape(str(item))}</div>'
        for i, item in enumerate(direita)
    )
    return f"""
<div class="match-container">
  <div class="match-col-left">{left_items}</div>
  <div class="match-col-space"></div>
  <div class="match-col-right">{right_items}</div>
</div>
"""


def _exercise_completar_html(dados: dict) -> str:
    frases = dados.get("frases", [dados.get("frase", "")] if "frase" in dados else [])
    opcoes = dados.get("opcoes", [])
    frases_html = ""
    for frase in frases:
        parts = str(frase).split("___")
        blank = '<span class="completar-blank">&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>'
        inner = blank.join(_html_escape.escape(p) for p in parts)
        frases_html += f'<div class="completar-frase">{inner}</div>'
    opcoes_str = " &nbsp;/&nbsp; ".join(_html_escape.escape(str(o)) for o in opcoes)
    return f"""
<div class="completar-frases">{frases_html}</div>
<div class="completar-opcoes">
  <span class="completar-opcoes-label">Palavras:</span>{opcoes_str}
</div>
"""


def _exercise_sequencia_html(dados: dict) -> str:
    items = dados.get("items", [])
    parts = []
    for i, item in enumerate(items):
        if str(item) == "???":
            parts.append('<span class="seq-item blank">???</span>')
        else:
            parts.append(f'<span class="seq-item">{_html_escape.escape(str(item))}</span>')
        if i < len(items) - 1:
            parts.append('<span class="seq-arrow">→</span>')
    return f'<div class="sequence-container">{"".join(parts)}</div>'


def _exercise_tabela_html(dados: dict) -> str:
    colunas = dados.get("colunas", [])
    raw_linhas = dados.get("linhas", 5)
    num_linhas = int(raw_linhas[0] if isinstance(raw_linhas, list) else raw_linhas)
    headers = "".join(f'<th>{_html_escape.escape(str(c))}</th>' for c in colunas)
    row = "".join("<td></td>" for _ in colunas)
    rows = "".join(f"<tr>{row}</tr>" for _ in range(num_linhas))
    return f"""
<table class="response-table">
  <thead><tr>{headers}</tr></thead>
  <tbody>{rows}</tbody>
</table>
"""


def _exercise_html(exercicio: dict) -> str:
    numero = exercicio.get("numero", "?")
    titulo = _html_escape.escape(str(exercicio.get("titulo", "")))
    descricao = _html_escape.escape(str(exercicio.get("descricao", "")))
    instrucoes = exercicio.get("instrucoes", [])
    tipo = exercicio.get("tipo", "texto")
    categoria = exercicio.get("categoria")
    dados = exercicio.get("dados_visuais") or {}
    espaco = exercicio.get("espaco_resposta", "linha")

    icone = _pdf_assets.icon_for(categoria, tipo)
    cat_label = _html_escape.escape(str(categoria)) if categoria else ""
    cat_html = f'<div class="ex-cat">{cat_label}</div>' if cat_label else ""
    header = (
        f'{cat_html}'
        f'<div class="ex-header"><span class="ex-ic">{icone}</span>'
        f'<span class="ex-title">Exercício {numero} · {titulo}</span></div>'
    )
    desc_html = f'<p class="exercise-desc">{descricao}</p>' if descricao else ""

    steps_html = ""
    if instrucoes:
        steps = "".join(
            f'<div class="exercise-step">{i + 1}. {_html_escape.escape(str(p))}</div>'
            for i, p in enumerate(instrucoes)
        )
        steps_html = f'<div class="exercise-steps-title">Como fazer:</div>{steps}'

    if tipo == "ligar":
        content_html = _exercise_ligar_html(dados)
    elif tipo == "completar":
        content_html = _exercise_completar_html(dados)
    elif tipo == "sequencia":
        content_html = _exercise_sequencia_html(dados)
    elif tipo == "tabela":
        content_html = _exercise_tabela_html(dados)
    else:
        content_html = _answer_space_html(espaco)

    return f"""
<div class="exercise">
  {header}
  {desc_html}
  {steps_html}
  {content_html}
</div>
"""


def render_apostila_html(topico: dict, conteudo_json: str, capa_img=None) -> str:
    conteudo = json.loads(conteudo_json)
    exercicios = conteudo.get("exercicios", [])
    num_exercicios = conteudo.get("num_exercicios", len(exercicios))
    nome_topico = topico.get("nome", topico.get("name", ""))
    fases = conteudo.get("fases", [])
    tem_premium = bool(fases)

    cover = _cover_html(topico, num_exercicios, capa_img=capa_img)
    nome_escaped = _html_escape.escape(nome_topico)

    if tem_premium:
        apresentacao = _apresentacao_html(conteudo.get("apresentacao", ""))
        indice = _indice_html(fases)

        ex_por_numero = {e["numero"]: e for e in exercicios}

        conteudo_interno = ""
        for fase in fases:
            conteudo_interno += _fase_abertura_html(fase)
            numeros = fase.get("exercicios_numeros", [])
            fase_exercicios = [ex_por_numero[n] for n in numeros if n in ex_por_numero]
            exercises_html = _pdf_assets.divider_svg().join(
                _exercise_html(e) for e in fase_exercicios
            )
            conteudo_interno += f'<div class="exercises-block">{exercises_html}</div>'

        rotina = _rotina_semanal_html(conteudo.get("rotina_semanal", {}))
        gabarito = _gabarito_html(conteudo.get("gabarito", []))
        contracapa = _contracapa_html()

        body = f"{cover}{apresentacao}{indice}{conteudo_interno}{rotina}{gabarito}{contracapa}"
    else:
        instructions = _instructions_html(nome_topico, num_exercicios)
        exercises_html = _pdf_assets.divider_svg().join(
            _exercise_html(e) for e in exercicios
        )
        body = f"{cover}{instructions}<div class=\"exercises-block\">{exercises_html}</div>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Apostila de {nome_escaped} — Cognivita</title>
  <style>{_css()}</style>
</head>
<body>
  {body}
</body>
</html>
"""


if __name__ == "__main__":
    import os

    _topico = {"id": 1, "nome": "Memória", "slug": "memoria"}
    _exercicios = [
        {
            "numero": 1, "tipo": "texto", "titulo": "Recordar Palavras",
            "descricao": "Leia as palavras e tente memorizá-las.",
            "instrucoes": ["Leia com calma", "Cubra e escreva abaixo"],
            "espaco_resposta": "linha", "dados_visuais": None,
        },
        {
            "numero": 2, "tipo": "ligar", "titulo": "Ligar Palavras",
            "descricao": "Ligue cada item ao seu par correto.",
            "instrucoes": ["Escreva o número ao lado da letra."],
            "espaco_resposta": "visual",
            "dados_visuais": {"esquerda": ["Cachorro", "Rosa", "Avião"], "direita": ["Flor", "Animal", "Veículo"]},
        },
        {
            "numero": 3, "tipo": "completar", "titulo": "Complete a Frase",
            "descricao": "Escolha a palavra correta para completar as frases.",
            "instrucoes": ["Escreva a palavra no espaço indicado por ___."],
            "espaco_resposta": "visual",
            "dados_visuais": {
                "frases": ["O ___ nasce de manhã e se põe à tarde.", "À noite brilham as ___."],
                "opcoes": ["sol", "estrelas", "lua", "nuvens"],
            },
        },
        {
            "numero": 4, "tipo": "sequencia", "titulo": "Complete a Sequência",
            "descricao": "Qual elemento completa esta sequência?",
            "instrucoes": ["Escreva sua resposta no espaço com ???."],
            "espaco_resposta": "visual",
            "dados_visuais": {"items": ["Primavera", "Verão", "???", "Inverno"]},
        },
        {
            "numero": 5, "tipo": "tabela", "titulo": "Preencha a Tabela",
            "descricao": "Complete a tabela abaixo.",
            "instrucoes": ["Preencha cada célula."],
            "espaco_resposta": "visual",
            "dados_visuais": {"colunas": ["Dia", "Atividade", "Humor"], "linhas": 4},
        },
    ]
    _conteudo = json.dumps(
        {"topico": "Memória", "num_exercicios": 5, "exercicios": _exercicios},
        ensure_ascii=False,
    )
    html_out = render_apostila_html(_topico, _conteudo)
    out_path = "output/test_render.html"
    os.makedirs("output", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"HTML gerado em: {out_path}")
