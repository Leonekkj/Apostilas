"""
generator/cp_html_render.py
Renderer premium de caça-palavras: HTML/CSS → Playwright → PDF A4.

Identidade visual CogniVita (mesma paleta/tipografia de html_render.py).
Capa usa arte de IA se existir em assets/capas_ia/{tema}.(png|jpg|jpeg|webp)
— gerada manualmente pelo usuário no Gemini (ver assets/capas_ia/PROMPTS.md).
Sem arte, a capa sai num design 100% CSS com motivo de grade de letras.
"""

import base64
import random
from pathlib import Path

COLOR_DARK = "#0C3322"
COLOR_GREEN = "#1B6B4A"
COLOR_BG = "#F7F3EC"
COLOR_TEXT = "#1A2820"
COLOR_MUTED = "#6B7E76"
COLOR_BORDER = "#E0E8E4"
COLOR_LIGHT_GREEN = "#D4EDE3"

_NIVEL_LABEL = {"facil": "Fácil", "medio": "Médio", "dificil": "Difícil", "gigante": "Gigante"}

_CAPAS_DIR = Path(__file__).parent.parent / "assets" / "capas_ia"


_MIMES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def file_data_uri(path) -> str | None:
    """Converte um arquivo de imagem local em data URI base64."""
    p = Path(path)
    if not p.exists():
        return None
    mime = _MIMES.get(p.suffix.lower(), "image/jpeg")
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _capa_data_uri(tema: str) -> str | None:
    """Carrega a arte de capa do tema como data URI base64 (se existir)."""
    for ext in _MIMES:
        p = _CAPAS_DIR / f"{tema}{ext}"
        if p.exists():
            return file_data_uri(p)
    return None


def _css(tamanho: int) -> str:
    # 2 puzzles por página: célula dimensionada para meia página (~106mm úteis)
    cell_mm = round(min(8.2, 106 / tamanho), 2)
    grid_font = f"{round(cell_mm * 1.8, 1)}pt"
    # gabarito 12 por página (3 colunas × 4 linhas)
    mini_cell = round(min(3.6, 52 / tamanho), 2)
    return f"""
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400&family=DM+Sans:wght@300;400;500;700&display=swap');

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'DM Sans', Arial, sans-serif; color: {COLOR_TEXT}; }}

.page {{
  width: 210mm; height: 296.7mm;
  page-break-after: always;
  background: {COLOR_BG};
  padding: 14mm 18mm;
  position: relative;
  overflow: hidden;
}}

/* ===== CAPA ===== */
.page.cover {{ padding: 0; background: {COLOR_DARK}; }}
.cover-art {{
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: cover;
}}
.cover-shade {{
  position: absolute; inset: 0;
  background: linear-gradient(180deg,
    rgba(12,51,34,0.30) 0%, rgba(12,51,34,0.05) 28%,
    rgba(12,51,34,0.15) 52%, rgba(12,51,34,0.88) 78%, rgba(12,51,34,0.97) 100%);
}}
.cover-letters {{
  position: absolute; inset: 0;
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  align-content: space-evenly; justify-items: center;
  padding: 24mm 14mm 110mm 14mm;
  font-family: 'DM Sans', sans-serif; font-weight: 700;
  font-size: 26pt; color: rgba(255,255,255,0.10);
}}
.cover-letters .hit {{
  color: {COLOR_LIGHT_GREEN};
  background: rgba(27,107,74,0.55);
  border-radius: 4mm;
  padding: 1mm 2.6mm;
}}
.cover-content {{
  position: absolute; left: 0; right: 0; bottom: 0;
  padding: 0 18mm 14mm 18mm;
  text-align: center; color: #fff;
}}
.cover-brand {{
  position: absolute; top: 0; left: 0; right: 0;
  text-align: center;
  padding: 9mm 0 4mm 0;
  font-size: 11pt; font-weight: 500;
  letter-spacing: 0.34em; text-transform: uppercase;
  color: rgba(255,255,255,0.92);
  text-shadow: 0 1px 6px rgba(12,51,34,0.6);
}}
.cover-kicker {{
  font-size: 10.5pt; font-weight: 500;
  letter-spacing: 0.26em; text-transform: uppercase;
  color: {COLOR_LIGHT_GREEN}; margin-bottom: 4mm;
}}
.cover-title {{
  font-family: 'Cormorant Garamond', serif;
  font-weight: 600; font-size: 46pt; line-height: 1.02;
  margin-bottom: 3mm;
}}
.cover-tema {{
  font-family: 'Cormorant Garamond', serif; font-style: italic;
  font-size: 19pt; color: rgba(255,255,255,0.92);
  margin-bottom: 8mm;
}}
.cover-chips {{ display: flex; justify-content: center; gap: 4mm; margin-bottom: 9mm; }}
.chip {{
  border: 1px solid rgba(255,255,255,0.45);
  border-radius: 99px;
  padding: 2.2mm 5.5mm;
  font-size: 10pt; font-weight: 500; letter-spacing: 0.08em;
  text-transform: uppercase; color: #fff;
}}
.chip.solid {{ background: {COLOR_GREEN}; border-color: {COLOR_GREEN}; }}
.cover-rule {{ width: 42mm; border: none; border-top: 1px solid rgba(255,255,255,0.4); margin: 0 auto 4.5mm auto; }}
.cover-domain {{
  font-family: 'Cormorant Garamond', serif; font-style: italic;
  font-size: 12pt; color: rgba(255,255,255,0.85);
}}

/* Capa com a ARTE DO LIVRO (mesma arte das fotos dos anúncios), página inteira */
.cover-art-full {{
  display: block;
  width: 210mm; height: 296.7mm;
  object-fit: cover;
}}

/* ===== COMO JOGAR ===== */
.section-band {{
  background: {COLOR_DARK}; color: #C8DDD0;
  font-size: 10.5pt; font-weight: 500;
  letter-spacing: 0.22em; text-transform: uppercase;
  padding: 3mm 5mm; margin-bottom: 8mm;
}}
.howto-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 24pt; font-weight: 600; color: {COLOR_DARK};
  margin-bottom: 6mm;
}}
.howto p {{ font-size: 13pt; line-height: 1.75; margin-bottom: 5mm; }}
.howto-tips {{
  background: #fff; border: 1px solid {COLOR_BORDER};
  border-left: 3px solid {COLOR_GREEN};
  border-radius: 3mm; padding: 6mm 7mm; margin-top: 6mm;
}}
.howto-tips h3 {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 16pt; color: {COLOR_GREEN}; margin-bottom: 3mm;
}}
.howto-tips li {{ font-size: 12.5pt; line-height: 1.8; margin-left: 6mm; }}
.dir-row {{ display: flex; gap: 5mm; margin: 7mm 0; }}
.dir-card {{
  flex: 1; text-align: center; background: #fff;
  border: 1px solid {COLOR_BORDER}; border-radius: 3mm; padding: 5mm 2mm;
}}
.dir-card .arrow {{ font-size: 21pt; color: {COLOR_GREEN}; }}
.dir-card .lbl {{ font-size: 10.5pt; color: {COLOR_MUTED}; margin-top: 1.5mm; }}

/* ===== PUZZLES (2 por página) ===== */
.page.puzzles {{ padding: 10mm 18mm; }}
.pz-block {{ height: 136mm; }}
.pz-block + .pz-block {{ border-top: 1px solid {COLOR_BORDER}; padding-top: 4mm; }}
.pz-head {{
  display: flex; align-items: baseline; justify-content: space-between;
  border-bottom: 1.5px solid {COLOR_DARK};
  padding-bottom: 1.5mm; margin-bottom: 3mm;
}}
.pz-num {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 15pt; font-weight: 600; color: {COLOR_DARK};
}}
.pz-num small {{ font-size: 9.5pt; color: {COLOR_MUTED}; font-family: 'DM Sans', sans-serif; font-weight: 400; }}
.pz-nivel {{
  color: {COLOR_GREEN};
  font-size: 8.5pt; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
}}
.grid-wrap {{ display: flex; justify-content: center; margin-bottom: 2.5mm; }}
table.grid {{
  border-collapse: separate; border-spacing: 0;
  border: 2px solid {COLOR_DARK}; border-radius: 2mm;
  background: #fff; overflow: hidden;
}}
table.grid td {{
  width: {cell_mm}mm; height: {cell_mm}mm;
  text-align: center; vertical-align: middle;
  font-family: 'DM Sans', sans-serif; font-weight: 500;
  font-size: {grid_font}; color: {COLOR_TEXT};
  border: 0.5px solid {COLOR_BORDER};
}}
.words {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 1.6mm; }}
.word {{
  background: #fff; border: 1px solid {COLOR_BORDER};
  border-bottom: 1.5px solid {COLOR_GREEN};
  border-radius: 1.5mm; padding: 0.8mm 2.8mm;
  font-size: 10pt; font-weight: 500; letter-spacing: 0.04em;
}}
.pz-foot {{
  position: absolute; left: 18mm; right: 18mm; bottom: 5mm;
  display: flex; justify-content: space-between;
  font-size: 8.5pt; color: {COLOR_MUTED};
}}
.pz-foot .brand {{ font-family: 'Cormorant Garamond', serif; font-style: italic; font-size: 9.5pt; }}

/* ===== GABARITO (12 por página: 3 × 4) ===== */
.gab-grid-row {{ display: flex; justify-content: space-around; margin-bottom: 4mm; }}
.gab-item {{ text-align: center; }}
.gab-item .cap {{
  font-size: 8.5pt; font-weight: 700; color: {COLOR_GREEN}; margin-bottom: 1mm;
}}
table.mini {{ border-collapse: collapse; border: 1px solid {COLOR_DARK}; background: #fff; }}
table.mini td {{
  width: {mini_cell}mm; height: {mini_cell}mm;
  text-align: center; vertical-align: middle;
  font-size: 4.5pt; font-weight: 700;
  border: 0.2px solid {COLOR_BORDER};
}}
table.mini td.hit {{ background: {COLOR_GREEN}; color: #fff; }}
table.mini td.off {{ color: transparent; background: #F2EEE6; }}

/* ===== CONTRACAPA (clara — página escura em P&B desperdiça toner) ===== */
.page.back {{
  background: {COLOR_BG}; color: {COLOR_DARK};
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center;
}}
.back-logo {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 38pt; font-weight: 600; letter-spacing: 0.08em;
  margin-bottom: 5mm;
}}
.back-tag {{
  font-size: 11pt; font-weight: 300; letter-spacing: 0.2em;
  text-transform: uppercase; color: {COLOR_GREEN}; margin-bottom: 12mm;
}}
.back-domain {{
  font-family: 'Cormorant Garamond', serif; font-style: italic;
  font-size: 13pt; color: {COLOR_MUTED};
}}
"""


def _cover_html(produto_nome: str, tema: str, dificuldade: str, n: int, capa_img=None) -> str:
    nivel = _NIVEL_LABEL.get(dificuldade, dificuldade.title())
    tema_label = tema.replace("_", " ").title()

    # Arte do livro (prioridade máxima): a mesma capa que aparece nas fotos
    # dos anúncios, em página inteira — a arte já traz marca, título e rodapé
    if capa_img:
        foto = file_data_uri(capa_img)
        if foto:
            return f'<div class="page cover"><img class="cover-art-full" src="{foto}" alt=""></div>'

    art = _capa_data_uri(tema)

    if art:
        fundo = f'<img class="cover-art" src="{art}" alt="">'
    else:
        # Motivo CSS: grade de letras com a palavra do tema destacada
        palavra = (tema_label.upper().replace(" ", "") or "COGNITIVO")[:10]
        rng = random.Random(tema)  # determinístico por tema
        letras = []
        linha_destaque = 3
        col_ini = max(0, (10 - len(palavra)) // 2)
        for r in range(7):
            for c in range(10):
                if r == linha_destaque and col_ini <= c < col_ini + len(palavra):
                    letras.append(f'<span class="hit">{palavra[c - col_ini]}</span>')
                else:
                    letras.append(f"<span>{rng.choice('ABCDEFGHIJLMNOPRSTUV')}</span>")
        fundo = f'<div class="cover-letters">{"".join(letras)}</div>'

    return f"""
<div class="page cover">
  {fundo}
  <div class="cover-shade"></div>
  <div class="cover-brand">C O G N I V I T A</div>
  <div class="cover-content">
    <div class="cover-kicker">Estimulação Cognitiva · 60+</div>
    <div class="cover-title">Caça-Palavras</div>
    <div class="cover-tema">{tema_label} — Nível {nivel}</div>
    <div class="cover-chips">
      <span class="chip solid">{n} puzzles</span>
      <span class="chip">Letra grande</span>
      <span class="chip">Gabarito incluído</span>
    </div>
    <hr class="cover-rule">
    <div class="cover-domain">cognivita.com.br</div>
  </div>
</div>"""


def _howto_html(dificuldade: str) -> str:
    direcoes = {
        "facil":   [("→", "Horizontal"), ("↓", "Vertical")],
        "medio":   [("→", "Horizontal"), ("↓", "Vertical"), ("↘", "Diagonal")],
        "dificil": [("→", "Horizontal"), ("↓", "Vertical"), ("↘", "Diagonal"), ("←", "Invertida")],
        "gigante": [("→", "Horizontal"), ("↓", "Vertical"), ("↘", "Diagonal")],
    }.get(dificuldade, [("→", "Horizontal"), ("↓", "Vertical")])
    cards = "".join(
        f'<div class="dir-card"><div class="arrow">{a}</div><div class="lbl">{l}</div></div>'
        for a, l in direcoes
    )
    return f"""
<div class="page howto">
  <div class="section-band">Como Jogar</div>
  <div class="howto-title">Bem-vindo ao seu momento de exercício mental</div>
  <p>Em cada página você encontrará uma grade de letras e, abaixo dela, a lista de
  palavras escondidas. Encontre cada palavra na grade e circule-a com lápis ou caneta.</p>
  <p>As palavras podem aparecer nas seguintes direções:</p>
  <div class="dir-row">{cards}</div>
  <div class="howto-tips">
    <h3>Dicas para aproveitar melhor</h3>
    <ul>
      <li>Reserve um momento tranquilo do dia, com boa iluminação.</li>
      <li>Comece procurando as palavras mais longas — elas são mais fáceis de localizar.</li>
      <li>Risque da lista cada palavra encontrada.</li>
      <li>Não tenha pressa: o exercício vale mais do que a velocidade.</li>
      <li>O gabarito completo está nas últimas páginas.</li>
    </ul>
  </div>
</div>"""


def _puzzle_block(puzzle: dict, numero: int, total: int, dificuldade: str) -> str:
    """Bloco compacto de meia página — 2 puzzles por página para reduzir custo de impressão."""
    nivel = _NIVEL_LABEL.get(dificuldade, dificuldade.title())
    linhas = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
        for row in puzzle["grid"]
    )
    chips = "".join(f'<span class="word">{p}</span>' for p in sorted(puzzle["palavras"]))
    return f"""
<div class="pz-block">
  <div class="pz-head">
    <div class="pz-num">Puzzle {numero:02d} <small>de {total} · {len(puzzle["palavras"])} palavras</small></div>
    <div class="pz-nivel">Nível {nivel}</div>
  </div>
  <div class="grid-wrap"><table class="grid">{linhas}</table></div>
  <div class="words">{chips}</div>
</div>"""


def _puzzle_pages(puzzles: list, dificuldade: str, tema: str) -> str:
    """Agrupa puzzles 2 por página."""
    tema_label = tema.replace("_", " ").title()
    total = len(puzzles)
    paginas = []
    for i in range(0, total, 2):
        blocos = "".join(
            _puzzle_block(puzzles[i + k], i + k + 1, total, dificuldade)
            for k in (0, 1) if i + k < total
        )
        rodape = (f'<div class="pz-foot"><span class="brand">CogniVita</span>'
                  f'<span>Caça-Palavras {tema_label} · pág. {i // 2 + 1}</span></div>')
        paginas.append(f'<div class="page puzzles">{blocos}{rodape}</div>')
    return "".join(paginas)


def _gabarito_html(puzzles: list) -> str:
    paginas = []
    POR_PAGINA = 12  # 3 colunas × 4 linhas
    POR_LINHA = 3
    for i in range(0, len(puzzles), POR_PAGINA):
        lote = puzzles[i:i + POR_PAGINA]
        rows = []
        for j in range(0, len(lote), POR_LINHA):
            itens = []
            for k in range(j, min(j + POR_LINHA, len(lote))):
                pz = lote[k]
                cells = "".join(
                    "<tr>" + "".join(
                        f'<td class="hit">{c}</td>' if c != "." else '<td class="off">·</td>'
                        for c in row
                    ) + "</tr>"
                    for row in pz["gabarito"]
                )
                itens.append(
                    f'<div class="gab-item"><div class="cap">#{i + k + 1:02d}</div>'
                    f'<table class="mini">{cells}</table></div>'
                )
            rows.append(f'<div class="gab-grid-row">{"".join(itens)}</div>')
        band = '<div class="section-band">Gabarito</div>' if i == 0 else ""
        paginas.append(f'<div class="page">{band}{"".join(rows)}</div>')
    return "".join(paginas)


def _back_html() -> str:
    # "Editora CogniVita" explícito atende ao requisito da Amazon (página interna
    # com nome da editora) para isenção de GTIN de livro.
    return """
<div class="page back">
  <div class="back-logo">CogniVita</div>
  <div class="back-tag">Estimulação Cognitiva · Envelhecimento Saudável</div>
  <div class="back-domain">cognivita.com.br</div>
  <div style="margin-top:14mm; font-size:10pt; color:#6B7E76; line-height:1.7;">
    Editora CogniVita<br>
    1ª edição · 2026 · Impresso no Brasil<br>
    © CogniVita — Todos os direitos reservados
  </div>
</div>"""


def render_cp_html(produto_nome: str, tema: str, dificuldade: str, puzzles: list, capa_img=None) -> str:
    """Monta o HTML completo da apostila de caça-palavras (capa→gabarito→contracapa).

    capa_img: caminho local da foto do anúncio — quando presente, a capa do PDF
    é a mesma arte que o cliente viu no ML.
    """
    tamanho = len(puzzles[0]["grid"]) if puzzles else 15
    partes = [
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{_css(tamanho)}</style></head><body>",
        _cover_html(produto_nome, tema, dificuldade, len(puzzles), capa_img=capa_img),
        _howto_html(dificuldade),
        _puzzle_pages(puzzles, dificuldade, tema),
        _gabarito_html(puzzles),
        _back_html(),
        "</body></html>",
    ]
    return "".join(partes)
