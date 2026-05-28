"""
generator/html_render.py
Converte conteúdo de apostila para HTML pronto para impressão via Playwright.
"""

import json
import html as _html_escape

COLOR_DARK = "#0C3322"
COLOR_GREEN = "#1B6B4A"
COLOR_BG = "#F7F3EC"
COLOR_TEXT = "#1A2820"
COLOR_MUTED = "#6B7E76"
COLOR_BORDER = "#E0E8E4"
COLOR_LIGHT_GREEN = "#D4EDE3"


def _css() -> str:
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,400&family=DM+Sans:wght@300;400;500&display=swap');

@page {{
  size: A4;
  margin: 18mm 20mm 20mm 20mm;
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: 'DM Sans', Arial, sans-serif;
  color: {COLOR_TEXT};
  font-size: 12.5pt;
  line-height: 1.65;
  background: {COLOR_BG};
}}

.page {{ page-break-after: always; background: {COLOR_BG}; }}

/* === CAPA === */
.cover {{
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  min-height: 250mm;
  background: {COLOR_BG};
}}
.cover-brand-bar {{
  width: 100%;
  background: {COLOR_DARK};
  color: #C8DDD0;
  font-family: 'DM Sans', sans-serif;
  font-size: 11pt;
  font-weight: 400;
  letter-spacing: 0.28em;
  text-transform: uppercase;
  padding: 11px 0;
  margin-bottom: 28mm;
}}
.cover-logo {{
  font-family: 'Cormorant Garamond', serif;
  font-weight: 600;
  font-size: 42pt;
  color: {COLOR_DARK};
  letter-spacing: 0.08em;
  line-height: 1.1;
  margin-bottom: 5mm;
}}
.cover-rule {{
  width: 50%;
  border: none;
  border-top: 1px solid {COLOR_GREEN};
  margin: 0 auto 10mm auto;
}}
.cover-tagline {{
  font-family: 'DM Sans', sans-serif;
  font-weight: 300;
  font-size: 10pt;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: {COLOR_MUTED};
  margin-bottom: 10mm;
}}
.cover-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 28pt;
  font-weight: 400;
  color: {COLOR_TEXT};
  margin-bottom: 4mm;
  line-height: 1.2;
}}
.cover-subtitle {{
  font-family: 'DM Sans', sans-serif;
  font-weight: 300;
  font-size: 13pt;
  color: {COLOR_MUTED};
  margin-bottom: 32mm;
}}
.cover-footer-bar {{
  width: 100%;
  border-top: 1px solid {COLOR_BORDER};
  background: white;
  color: {COLOR_GREEN};
  font-family: 'DM Sans', sans-serif;
  font-size: 10pt;
  font-weight: 500;
  letter-spacing: 0.06em;
  padding: 9px 0;
  margin-bottom: 4mm;
}}
.cover-domain {{
  font-family: 'Cormorant Garamond', serif;
  font-style: italic;
  font-size: 11pt;
  color: {COLOR_MUTED};
}}

/* === INSTRUÇÕES === */
.instructions-header {{
  background: {COLOR_DARK};
  color: #C8DDD0;
  font-family: 'DM Sans', sans-serif;
  font-size: 10pt;
  font-weight: 500;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 9px 14px;
  margin-bottom: 8mm;
}}
.instructions-body {{
  font-size: 12.5pt;
  text-align: justify;
  margin-bottom: 4mm;
  color: {COLOR_TEXT};
}}
.instructions-tips-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 14pt;
  font-weight: 600;
  color: {COLOR_GREEN};
  margin: 5mm 0 3mm 0;
}}
.instructions-tip {{
  margin-bottom: 3mm;
  padding-left: 4mm;
  color: {COLOR_TEXT};
}}
.instructions-rule {{
  border: none;
  border-top: 1px solid {COLOR_BORDER};
  margin: 6mm 0;
}}
.instructions-footer {{
  font-size: 11pt;
  text-align: justify;
  color: {COLOR_MUTED};
}}

/* === EXERCÍCIOS === */
.exercise {{
  margin-bottom: 8mm;
  page-break-inside: avoid;
  break-inside: avoid;
}}
.exercises-block {{
  /* Fluxo natural — Playwright gerencia quebras de página */
}}
.exercise-header {{
  background: {COLOR_DARK};
  color: #C8DDD0;
  font-family: 'DM Sans', sans-serif;
  font-size: 10pt;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 7px 14px;
  margin-bottom: 4mm;
}}
.exercise-desc {{
  font-size: 12.5pt;
  text-align: justify;
  margin-bottom: 3mm;
  color: {COLOR_TEXT};
}}
.exercise-steps-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 13pt;
  font-weight: 600;
  color: {COLOR_GREEN};
  margin-bottom: 1mm;
}}
.exercise-step {{
  font-size: 12pt;
  padding-left: 6mm;
  margin-bottom: 2mm;
  color: {COLOR_TEXT};
}}
.answer-label {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 12pt;
  font-weight: 600;
  color: {COLOR_GREEN};
  margin: 3mm 0 2mm 0;
}}
.answer-line {{
  border-top: 1px solid {COLOR_BORDER};
  margin-bottom: 7mm;
}}
.answer-box {{
  border: 1px solid {COLOR_BORDER};
  background: white;
  height: 50mm;
  width: 140mm;
  margin: 2mm 0 4mm 0;
}}
.answer-bullets {{
  list-style: none;
  margin: 2mm 0;
}}
.answer-bullets li {{
  border-bottom: 1px solid {COLOR_BORDER};
  padding: 5mm 0 1mm 0;
  margin-bottom: 2mm;
  font-size: 12.5pt;
}}
.exercise-separator {{
  border: none;
  border-top: 1px solid {COLOR_BORDER};
  margin: 6mm 0;
}}

/* === LIGAR COLUNAS === */
.match-container {{
  display: flex;
  gap: 0;
  margin: 4mm 0;
  width: 100%;
}}
.match-col-left, .match-col-right {{
  flex: 1;
}}
.match-col-space {{
  flex: 1;
  border-left: 1px dashed {COLOR_BORDER};
  border-right: 1px dashed {COLOR_BORDER};
  margin: 0 4mm;
}}
.match-item {{
  border-bottom: 1px solid {COLOR_BORDER};
  padding: 7px 4px;
  font-size: 12.5pt;
}}
.match-item-num {{
  font-weight: 500;
  color: {COLOR_GREEN};
  margin-right: 4px;
}}
.match-item-letter {{
  font-weight: 500;
  color: {COLOR_GREEN};
  margin-right: 4px;
}}
.match-answer-blank {{
  display: inline-block;
  width: 28px;
  border-bottom: 1px solid {COLOR_TEXT};
  margin-left: 6px;
}}

/* === COMPLETAR LACUNAS === */
.completar-frases {{
  margin: 4mm 0;
}}
.completar-frase {{
  font-size: 13.5pt;
  line-height: 2.6;
  margin-bottom: 4mm;
  padding: 4px 0;
  border-bottom: 1px solid {COLOR_BORDER};
}}
.completar-blank {{
  display: inline-block;
  min-width: 80px;
  border-bottom: 1.5px solid {COLOR_TEXT};
  margin: 0 4px;
}}
.completar-opcoes {{
  font-size: 11pt;
  color: {COLOR_MUTED};
  margin-top: 3mm;
  padding: 7px 12px;
  border: 1px solid {COLOR_BORDER};
  background: white;
}}
.completar-opcoes-label {{
  font-weight: 500;
  color: {COLOR_GREEN};
  margin-right: 6px;
}}

/* === SEQUÊNCIA === */
.sequence-container {{
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 6mm 0;
  padding: 4mm 0;
}}
.seq-item {{
  border: 1.5px solid {COLOR_GREEN};
  padding: 8px 18px;
  font-size: 13pt;
  font-weight: 500;
  color: {COLOR_TEXT};
  background: white;
}}
.seq-item.blank {{
  border: 1.5px dashed {COLOR_BORDER};
  min-width: 80px;
  color: {COLOR_BORDER};
  text-align: center;
}}
.seq-arrow {{
  font-size: 14pt;
  color: {COLOR_MUTED};
}}

/* === TABELA === */
.response-table {{
  width: 100%;
  border-collapse: collapse;
  margin: 4mm 0;
  font-size: 11.5pt;
}}
.response-table th {{
  background: {COLOR_DARK};
  color: #C8DDD0;
  padding: 8px 12px;
  text-align: left;
  font-weight: 500;
  font-size: 10pt;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.response-table td {{
  border: 1px solid {COLOR_BORDER};
  height: 36px;
  padding: 4px 10px;
  background: white;
}}
.response-table tr:nth-child(even) td {{
  background: {COLOR_BG};
}}

/* === APRESENTAÇÃO === */
.apresentacao-body {{
  font-size: 13pt;
  line-height: 1.8;
  text-align: justify;
  color: {COLOR_TEXT};
}}
.apresentacao-body p {{
  margin-bottom: 5mm;
}}

/* === ÍNDICE === */
.indice {{
  margin-top: 4mm;
}}
.indice-item {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 1px dotted {COLOR_BORDER};
  padding: 5px 0;
  font-size: 13pt;
}}
.indice-fase-nome {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 14pt;
  color: {COLOR_TEXT};
}}
.indice-secao {{
  font-size: 10pt;
  font-weight: 500;
  color: {COLOR_GREEN};
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}

/* === ABERTURA DE FASE === */
.fase-abertura {{
  min-height: 200mm;
}}
.fase-bar {{
  background: {COLOR_DARK};
  padding: 14px 16px;
  margin-bottom: 8mm;
}}
.fase-num {{
  display: block;
  font-family: 'DM Sans', sans-serif;
  font-size: 9pt;
  font-weight: 500;
  color: {COLOR_LIGHT_GREEN};
  letter-spacing: 0.22em;
  text-transform: uppercase;
  margin-bottom: 2px;
}}
.fase-nome {{
  display: block;
  font-family: 'Cormorant Garamond', serif;
  font-size: 26pt;
  font-weight: 600;
  color: white;
  line-height: 1.1;
}}
.fase-secao-tag {{
  display: inline-block;
  border: 1px solid {COLOR_GREEN};
  color: {COLOR_GREEN};
  font-size: 9pt;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 3px 10px;
  margin-bottom: 5mm;
}}
.fase-objetivo {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 15pt;
  font-style: italic;
  color: {COLOR_MUTED};
  margin-bottom: 6mm;
  padding-bottom: 4mm;
  border-bottom: 1px solid {COLOR_BORDER};
}}
.fase-abertura-text {{
  font-size: 13pt;
  line-height: 1.8;
  text-align: justify;
  color: {COLOR_TEXT};
}}
.fase-abertura-text p {{
  margin-bottom: 4mm;
}}

/* === ROTINA SEMANAL === */
.rotina-texto {{
  font-size: 13pt;
  line-height: 1.7;
  text-align: justify;
  margin-bottom: 6mm;
  color: {COLOR_TEXT};
}}
.rotina-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12pt;
}}
.rotina-table th {{
  background: {COLOR_DARK};
  color: {COLOR_LIGHT_GREEN};
  padding: 8px 12px;
  text-align: left;
  font-weight: 500;
  font-size: 9.5pt;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}
.rotina-table td {{
  border: 1px solid {COLOR_BORDER};
  padding: 8px 12px;
  vertical-align: middle;
}}
.rotina-table tr:nth-child(even) td {{
  background: {COLOR_BG};
}}
.rotina-dia {{
  font-weight: 500;
  color: {COLOR_TEXT};
  min-width: 40mm;
}}
.rotina-sugestao {{
  color: {COLOR_MUTED};
}}
.rotina-check {{
  width: 16mm;
  text-align: center;
}}
.rotina-checkbox {{
  width: 14px;
  height: 14px;
  border: 1.5px solid {COLOR_BORDER};
  display: inline-block;
}}

/* === GABARITO === */
.gabarito-grid {{
  display: flex;
  flex-direction: column;
  gap: 3mm;
  margin-top: 4mm;
}}
.gabarito-item {{
  display: flex;
  gap: 6mm;
  align-items: baseline;
  padding: 5px 8px;
  border-bottom: 1px solid {COLOR_BORDER};
  font-size: 12pt;
}}
.gabarito-num {{
  font-weight: 700;
  color: {COLOR_GREEN};
  min-width: 20mm;
  font-size: 11pt;
}}
.gabarito-titulo {{
  color: {COLOR_MUTED};
  font-size: 10pt;
  min-width: 50mm;
}}
.gabarito-resposta {{
  color: {COLOR_TEXT};
  flex: 1;
}}

/* === CONTRACAPA === */
.contracapa {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 240mm;
  text-align: center;
  background: {COLOR_DARK};
}}
.contracapa-logo {{
  font-family: 'Cormorant Garamond', serif;
  font-weight: 600;
  font-size: 36pt;
  color: white;
  letter-spacing: 0.08em;
  margin-bottom: 4mm;
}}
.contracapa-rule {{
  width: 40%;
  border: none;
  border-top: 1px solid {COLOR_GREEN};
  margin: 0 auto 6mm auto;
}}
.contracapa-tagline {{
  font-family: 'DM Sans', sans-serif;
  font-size: 10pt;
  font-weight: 300;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: {COLOR_LIGHT_GREEN};
  margin-bottom: 3mm;
  opacity: 0.8;
}}
.contracapa-domain {{
  font-family: 'Cormorant Garamond', serif;
  font-style: italic;
  font-size: 13pt;
  color: {COLOR_LIGHT_GREEN};
  opacity: 0.7;
}}
"""


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
<div class="page contracapa">
  <div class="contracapa-logo">Cognivita</div>
  <hr class="contracapa-rule">
  <div class="contracapa-tagline">Coleção Bem Envelhecer</div>
  <div class="contracapa-domain">cognivita.com.br</div>
</div>
"""


def _cover_html(topico: dict, num_exercicios: int) -> str:
    nome = _html_escape.escape(topico.get("nome", topico.get("name", "")))
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
    lines = "".join('<div class="answer-line"></div>' for _ in range(8))
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
    num_linhas = dados.get("linhas", 5)
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
    dados = exercicio.get("dados_visuais") or {}
    espaco = exercicio.get("espaco_resposta", "linha")

    header = f'<div class="exercise-header">EXERCÍCIO {numero} — {titulo.upper()}</div>'
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


def render_apostila_html(topico: dict, conteudo_json: str) -> str:
    conteudo = json.loads(conteudo_json)
    exercicios = conteudo.get("exercicios", [])
    num_exercicios = conteudo.get("num_exercicios", len(exercicios))
    nome_topico = topico.get("nome", topico.get("name", ""))
    fases = conteudo.get("fases", [])
    tem_premium = bool(fases)

    cover = _cover_html(topico, num_exercicios)
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
            exercises_html = "".join(_exercise_html(e) for e in fase_exercicios)
            conteudo_interno += f'<div class="exercises-block">{exercises_html}</div>'

        rotina = _rotina_semanal_html(conteudo.get("rotina_semanal", {}))
        gabarito = _gabarito_html(conteudo.get("gabarito", []))
        contracapa = _contracapa_html()

        body = f"{cover}{apresentacao}{indice}{conteudo_interno}{rotina}{gabarito}{contracapa}"
    else:
        instructions = _instructions_html(nome_topico, num_exercicios)
        exercises_html = "".join(_exercise_html(e) for e in exercicios)
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
