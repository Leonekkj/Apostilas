"""
gerar_caca_palavras.py
Gera puzzles de caça-palavras e PDF via ReportLab.
"""
import json
import random
import unicodedata
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ──────────────────────────────────────────────────────
# Paleta visual
# ──────────────────────────────────────────────────────
C_BLUE       = HexColor("#2E6DA4")
C_BLUE_DARK  = HexColor("#1A4A72")
C_BLUE_LIGHT = HexColor("#EBF3FA")
C_SAGE       = HexColor("#5C8B6B")
C_WARM       = HexColor("#F8F7F2")
C_DARK       = HexColor("#2B2B2B")
C_MID        = HexColor("#5A5A5A")
C_LINE       = HexColor("#D5D5D5")
C_GRAY       = HexColor("#CCCCCC")
FB = "Helvetica-Bold"
FR = "Helvetica"
FI = "Helvetica-Oblique"
W, H = A4

# ──────────────────────────────────────────────────────
# Configurações por dificuldade
# ──────────────────────────────────────────────────────
CONFIGS = {
    "facil":   {"tamanho": 12, "num_palavras": 8,  "direcoes": ["H", "V"]},
    "medio":   {"tamanho": 15, "num_palavras": 12, "direcoes": ["H", "V", "D"]},
    "dificil": {"tamanho": 18, "num_palavras": 18, "direcoes": ["H", "V", "D", "HR", "VR", "DR"]},
    "gigante": {"tamanho": 15, "num_palavras": 12, "direcoes": ["H", "V", "D"]},
}

VOGAIS = "AEIOU"
CONSOANTES = "BCDFGHJKLMNPQRSTVWXYZ"
# Preenche vazios com mais vogais para facilitar leitura dos idosos
_FILL_POOL = VOGAIS * 3 + CONSOANTES


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def carregar_palavras(tema: str) -> list[str]:
    """Carrega palavras de content/palavras/{tema}.json, filtrando >12 chars."""
    base = Path(__file__).parent / "content" / "palavras"
    arquivo = base / f"{tema}.json"
    if not arquivo.exists():
        arquivo = base / "geral.json"
    data = json.loads(arquivo.read_text(encoding="utf-8"))
    return [_sem_acento(p.strip().upper()) for p in data["palavras"] if 3 <= len(p.strip()) <= 12]


# ──────────────────────────────────────────────────────
# Direções: (delta_row, delta_col)
# ──────────────────────────────────────────────────────
_DELTA = {
    "H":  (0,  1),   # →
    "HR": (0, -1),   # ←
    "V":  (1,  0),   # ↓
    "VR": (-1, 0),   # ↑
    "D":  (1,  1),   # ↘
    "DR": (1, -1),   # ↙
}


def _cabe(grid: list[list[str]], palavra: str, row: int, col: int, dr: int, dc: int) -> bool:
    """Retorna True se a palavra cabe na posição sem conflito de letras."""
    n = len(grid)
    for i, letra in enumerate(palavra):
        r, c = row + i * dr, col + i * dc
        if not (0 <= r < n and 0 <= c < n):
            return False
        if grid[r][c] not in ("", letra):
            return False
    return True


def _encaixar(grid: list[list[str]], gabarito: list[list[str]], palavra: str, row: int, col: int, dr: int, dc: int) -> None:
    """Escreve a palavra no grid e marca no gabarito."""
    for i, letra in enumerate(palavra):
        r, c = row + i * dr, col + i * dc
        grid[r][c] = letra
        gabarito[r][c] = letra


def _preencher_vazios(grid: list[list[str]]) -> None:
    """Preenche células vazias com letras aleatórias."""
    for row in grid:
        for i, cell in enumerate(row):
            if cell == "":
                row[i] = random.choice(_FILL_POOL)


def gerar_puzzles(tema: str, dificuldade: str, num_puzzles: int) -> list[dict]:
    """
    Gera lista de puzzles de caça-palavras.

    Returns:
        list de dicts com chaves: grid, palavras, gabarito
        - grid: list[list[str]]     — grade preenchida com letras
        - palavras: list[str]       — palavras escondidas no grid
        - gabarito: list[list[str]] — grid com só as palavras (vazios como '.')
    """
    cfg = CONFIGS.get(dificuldade, CONFIGS["medio"])
    tamanho = cfg["tamanho"]
    num_palavras = cfg["num_palavras"]
    direcoes = cfg["direcoes"]

    pool = carregar_palavras(tema)
    # Filtra palavras que cabem no grid
    pool = [p for p in pool if len(p) <= tamanho]
    random.shuffle(pool)

    puzzles = []
    usadas_global: set[str] = set()

    for _ in range(num_puzzles):
        grid = [[""] * tamanho for _ in range(tamanho)]
        gabarito = [["."] * tamanho for _ in range(tamanho)]
        palavras_encaixadas: list[str] = []

        # Pool local: evita repetir palavra no mesmo volume (até esgotar)
        disponiveis = [p for p in pool if p not in usadas_global]
        if len(disponiveis) < num_palavras:
            usadas_global.clear()
            disponiveis = pool[:]
        random.shuffle(disponiveis)

        for palavra in disponiveis:
            if len(palavras_encaixadas) >= num_palavras:
                break
            encaixou = False
            for _ in range(100):  # 100 tentativas por palavra
                dr, dc = _DELTA[random.choice(direcoes)]
                row = random.randint(0, tamanho - 1)
                col = random.randint(0, tamanho - 1)
                if _cabe(grid, palavra, row, col, dr, dc):
                    _encaixar(grid, gabarito, palavra, row, col, dr, dc)
                    palavras_encaixadas.append(palavra)
                    usadas_global.add(palavra)
                    encaixou = True
                    break

        _preencher_vazios(grid)
        puzzles.append({
            "grid":     grid,
            "palavras": palavras_encaixadas,
            "gabarito": gabarito,
        })

    return puzzles


def _s(name, **kw):
    return ParagraphStyle(name, **kw)


def _band(text, bg=None, fg=None, font=None, size=13, pad_v=7):
    bg   = bg   or C_BLUE_DARK
    fg   = fg   or white
    font = font or FB
    st = _s("_b", fontName=font, fontSize=size, textColor=fg,
            alignment=TA_CENTER, leading=size + 4)
    tbl = Table([[Paragraph(text, st)]], colWidths=[W - 30 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("TOPPADDING",    (0, 0), (-1, -1), pad_v),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad_v),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6 * mm),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6 * mm),
    ]))
    return tbl


def _hr(color=None, thickness=1, after=4):
    return HRFlowable(width="100%", thickness=thickness,
                      color=color or C_LINE, spaceAfter=after * mm)


def _renderizar_grid(grid: list[list[str]], gabarito: list[list[str]] | None = None, escala: float = 1.0) -> Table:
    """Converte grid em Table ReportLab. gabarito destaca letras das palavras."""
    tamanho = len(grid)
    # Tamanho de célula adaptado ao grid para caber na página (180mm útil)
    _tamanho_celula = {12: 13.5, 15: 11.0, 18: 9.0}
    cell_mm = _tamanho_celula.get(tamanho, 180 / tamanho)
    cell_size = cell_mm * mm * escala
    font_size = max(int(cell_mm * 0.7 * escala), 6)
    pad = max(int(1.5 * escala), 1)

    table_data = []
    for r, row in enumerate(grid):
        linha = []
        for c, letra in enumerate(row):
            is_palavra = gabarito is not None and gabarito[r][c] != "."
            style = _s("cell",
                fontName=FB if is_palavra else FR,
                fontSize=font_size,
                textColor=C_BLUE_DARK if is_palavra else C_DARK,
                alignment=TA_CENTER,
                leading=font_size + 2,
            )
            linha.append(Paragraph(letra, style))
        table_data.append(linha)

    tbl = Table(table_data,
                colWidths=[cell_size] * tamanho,
                rowHeights=[cell_size] * tamanho)
    style_cmds = [
        ("INNERGRID",    (0, 0), (-1, -1), 0.4, C_LINE),
        ("BOX",          (0, 0), (-1, -1), 1.5, C_BLUE),
        ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",   (0, 0), (-1, -1), white),
        ("TOPPADDING",   (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING",(0, 0), (-1, -1), pad),
        ("LEFTPADDING",  (0, 0), (-1, -1), pad),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
    ]
    if gabarito is not None:
        for r, row in enumerate(gabarito):
            for c, cell in enumerate(row):
                if cell != ".":
                    style_cmds.append(("BACKGROUND", (c, r), (c, r), C_BLUE_LIGHT))
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _cabecalho_pagina(produto_nome: str, numero: int, nivel_label: str) -> list:
    """Cabeçalho padrão CogniVita para cada página de puzzle."""
    return [
        Table(
            [[
                Paragraph("COGNIVITA", _s("bh", fontName=FB, fontSize=9, textColor=C_MID,
                                          alignment=TA_LEFT, leading=11)),
                Paragraph(f"Caça-Palavras  ·  {nivel_label}  ·  #{numero:02d}",
                          _s("bhr", fontName=FR, fontSize=9, textColor=C_MID,
                             alignment=TA_RIGHT, leading=11)),
            ]],
            colWidths=[(W - 30 * mm) / 2] * 2,
        ),
        _hr(color=C_BLUE, thickness=1.5, after=3),
    ]


def _caixa_palavras(palavras: list[str]) -> Table:
    """Renderiza a lista de palavras em caixa com fundo levemente colorido."""
    # Divide em até 3 colunas
    n = len(palavras)
    ncols = 3 if n >= 12 else 2 if n >= 6 else 1
    por_col = (n + ncols - 1) // ncols
    colunas = [palavras[i * por_col:(i + 1) * por_col] for i in range(ncols)]
    # Iguala altura
    max_rows = max(len(c) for c in colunas)
    for c in colunas:
        c += [""] * (max_rows - len(c))

    st_palavra = _s("pw", fontName=FB, fontSize=10, textColor=C_DARK,
                    alignment=TA_LEFT, leading=14)
    st_titulo  = _s("pt", fontName=FB, fontSize=9, textColor=C_MID,
                    alignment=TA_LEFT, leading=12)

    # Linha de título
    titulo_row = [Paragraph("ENCONTRE AS PALAVRAS:", st_titulo)] + [""] * (ncols - 1)
    linhas = [titulo_row] + [[Paragraph(c[r], st_palavra) for c in colunas] for r in range(max_rows)]

    col_w = (W - 30 * mm) / ncols
    tbl = Table(linhas, colWidths=[col_w] * ncols)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_WARM),
        ("BOX",           (0, 0), (-1, -1), 1, C_LINE),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, C_LINE),
        ("SPAN",          (0, 0), (-1, 0)),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _pagina_puzzle(puzzle: dict, numero: int, produto_nome: str, dificuldade: str) -> list:
    """Retorna lista de flowables ReportLab para uma página de puzzle."""
    nivel_label = {"facil": "Fácil", "medio": "Médio", "dificil": "Difícil", "gigante": "Gigante"}.get(dificuldade, "")

    flowables = []
    flowables.extend(_cabecalho_pagina(produto_nome, numero, nivel_label))
    flowables.append(Spacer(1, 4 * mm))
    flowables.append(_renderizar_grid(puzzle["grid"]))
    flowables.append(Spacer(1, 5 * mm))
    flowables.append(_caixa_palavras(puzzle["palavras"]))
    flowables.append(Spacer(1, 3 * mm))
    flowables.append(Paragraph("cognivita.com.br",
        _s("rod", fontName=FI, fontSize=8, textColor=C_MID,
           alignment=TA_RIGHT, leading=10)))
    flowables.append(PageBreak())
    return flowables


def gerar_pdf_caca_palavras(apostila_id: int, produto_nome: str, tema: str, dificuldade: str, num_puzzles: int) -> str:
    """Gera puzzles e PDF completo. Retorna caminho absoluto do PDF."""
    puzzles = gerar_puzzles(tema, dificuldade, num_puzzles)

    output_dir = Path(__file__).parent / "output" / "pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"apostila_{apostila_id}.pdf"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm,  bottomMargin=15 * mm,
    )

    nivel_label = {"facil": "Fácil", "medio": "Médio", "dificil": "Difícil", "gigante": "Gigante"}.get(dificuldade, "")
    tema_label  = tema.replace("_", " ").title()
    flowables   = []

    # ── Capa ──────────────────────────────────────────────────────────────
    flowables.append(_band("CAÇA-PALAVRAS", bg=C_BLUE_DARK, size=13))
    flowables.append(Spacer(1, 16 * mm))
    flowables.append(Paragraph("COGNIVITA",
        _s("lo", fontName=FB, fontSize=11, textColor=C_MID,
           alignment=TA_CENTER, leading=14, spaceAfter=2 * mm)))
    flowables.append(_hr(color=C_BLUE, thickness=2.5, after=6))
    flowables.append(Paragraph(produto_nome,
        _s("ti", fontName=FB, fontSize=26, textColor=C_DARK,
           alignment=TA_CENTER, leading=32, spaceAfter=4 * mm)))
    flowables.append(Spacer(1, 2 * mm))
    flowables.append(Paragraph(f"Nível {nivel_label}  ·  Tema: {tema_label}",
        _s("su", fontName=FR, fontSize=14, textColor=C_MID,
           alignment=TA_CENTER, leading=20)))
    flowables.append(Spacer(1, 20 * mm))
    flowables.append(Paragraph(str(len(puzzles)),
        _s("ba", fontName=FB, fontSize=52, textColor=C_BLUE,
           alignment=TA_CENTER, leading=58)))
    flowables.append(Paragraph("atividades originais",
        _s("ba2", fontName=FR, fontSize=14, textColor=C_MID,
           alignment=TA_CENTER, leading=20, spaceAfter=20 * mm)))
    flowables.append(Spacer(1, 10 * mm))
    flowables.append(_band(
        "Passatempo  ·  Estimulação Cognitiva  ·  Para Idosos 60+",
        bg=C_BLUE_LIGHT, fg=C_BLUE_DARK, font=FR, size=11))
    flowables.append(Spacer(1, 3 * mm))
    flowables.append(Paragraph("cognivita.com.br",
        _s("fo", fontName=FI, fontSize=11, textColor=C_MID,
           alignment=TA_CENTER, leading=16)))
    flowables.append(PageBreak())

    # ── Puzzles ───────────────────────────────────────────────────────────
    for i, puzzle in enumerate(puzzles, start=1):
        flowables.extend(_pagina_puzzle(puzzle, i, produto_nome, dificuldade))

    # ── Gabaritos ─────────────────────────────────────────────────────────
    flowables.append(_band("GABARITO", bg=C_BLUE_DARK, size=13))
    flowables.append(Spacer(1, 5 * mm))

    estilo_num = _s("gn", fontName=FB, fontSize=8, textColor=C_MID,
                    alignment=TA_CENTER, leading=10)
    for i in range(0, len(puzzles), 4):
        lote = puzzles[i:i + 4]
        for j in range(0, len(lote), 2):
            cel_a = [Paragraph(f"#{i+j+1:02d}", estilo_num),
                     _renderizar_grid(lote[j]["grid"], lote[j]["gabarito"], escala=0.42)]
            if j + 1 < len(lote):
                cel_b = [Paragraph(f"#{i+j+2:02d}", estilo_num),
                         _renderizar_grid(lote[j+1]["grid"], lote[j+1]["gabarito"], escala=0.42)]
            else:
                cel_b = [Paragraph("", estilo_num), Spacer(1, 1)]
            tbl_gab = Table([[cel_a, cel_b]], colWidths=[(W - 30 * mm) / 2] * 2)
            tbl_gab.setStyle(TableStyle([
                ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            flowables.append(tbl_gab)
            flowables.append(Spacer(1, 5 * mm))
        if i + 4 < len(puzzles):
            flowables.append(PageBreak())

    doc.build(flowables)
    return str(pdf_path.resolve())
