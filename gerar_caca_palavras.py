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
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ──────────────────────────────────────────────────────
# Paleta visual
# ──────────────────────────────────────────────────────
C_BLUE       = HexColor("#2E6DA4")
C_BLUE_LIGHT = HexColor("#EBF3FA")
C_DARK       = HexColor("#2B2B2B")
C_GRAY       = HexColor("#CCCCCC")
FB = "Helvetica-Bold"
FR = "Helvetica"
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


def _renderizar_grid(grid: list[list[str]], gabarito: list[list[str]] | None = None, escala: float = 1.0) -> Table:
    """Converte grid em Table ReportLab. gabarito destaca letras das palavras."""
    tamanho = len(grid)
    cell_size = (14 * mm) * escala

    table_data = []
    for r, row in enumerate(grid):
        linha = []
        for c, letra in enumerate(row):
            is_palavra = gabarito is not None and gabarito[r][c] != "."
            style = ParagraphStyle(
                "cell",
                fontName=FB if is_palavra else FR,
                fontSize=int(11 * escala),
                textColor=C_DARK,
                alignment=TA_CENTER,
                leading=int(13 * escala),
            )
            linha.append(Paragraph(letra, style))
        table_data.append(linha)

    col_widths = [cell_size] * tamanho
    row_heights = [cell_size] * tamanho

    tbl = Table(table_data, colWidths=col_widths, rowHeights=row_heights)
    grid_style = [
        ("GRID",          (0, 0), (-1, -1), 0.5, C_GRAY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",    (0, 0), (-1, -1), white),
        ("TOPPADDING",    (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING",   (0, 0), (-1, -1), 1),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 1),
    ]
    if gabarito is not None:
        for r, row in enumerate(gabarito):
            for c, cell in enumerate(row):
                if cell != ".":
                    grid_style.append(("BACKGROUND", (c, r), (c, r), C_BLUE_LIGHT))
    tbl.setStyle(TableStyle(grid_style))
    return tbl


def _pagina_puzzle(puzzle: dict, numero: int, produto_nome: str, dificuldade: str) -> list:
    """Retorna lista de flowables ReportLab para uma página de puzzle."""
    nivel_label = {"facil": "Fácil", "medio": "Médio", "dificil": "Difícil", "gigante": "Médio"}.get(dificuldade, "")

    estilo_titulo = ParagraphStyle("titulo", fontName=FB, fontSize=13, textColor=C_BLUE,
                                   alignment=TA_CENTER, leading=16)
    estilo_sub    = ParagraphStyle("sub",    fontName=FR, fontSize=10, textColor=C_DARK,
                                   alignment=TA_CENTER, leading=13)
    estilo_lista  = ParagraphStyle("lista",  fontName=FB, fontSize=11, textColor=C_DARK,
                                   alignment=TA_LEFT, leading=15)

    flowables = []
    flowables.append(Paragraph(produto_nome, estilo_titulo))
    flowables.append(Paragraph(f"Puzzle #{numero} — Nível {nivel_label}", estilo_sub))
    flowables.append(Spacer(1, 6 * mm))
    flowables.append(_renderizar_grid(puzzle["grid"]))
    flowables.append(Spacer(1, 5 * mm))

    palavras = puzzle["palavras"]
    metade = (len(palavras) + 1) // 2
    col1 = "   ".join(palavras[:metade])
    col2 = "   ".join(palavras[metade:])
    flowables.append(Paragraph("Encontre as palavras:", estilo_sub))
    flowables.append(Spacer(1, 2 * mm))
    flowables.append(Paragraph(col1, estilo_lista))
    if col2:
        flowables.append(Paragraph(col2, estilo_lista))
    flowables.append(PageBreak())
    return flowables


def gerar_pdf_caca_palavras(apostila_id: int, produto_nome: str, tema: str, dificuldade: str, num_puzzles: int) -> str:
    """Gera puzzles e PDF completo. Retorna caminho absoluto do PDF."""
    puzzles = gerar_puzzles(tema, dificuldade, num_puzzles)

    output_dir = Path(__file__).parent / "output" / "pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"apostila_{apostila_id}.pdf"

    estilo_capa_titulo = ParagraphStyle("cap_t", fontName=FB, fontSize=22, textColor=white,
                                        alignment=TA_CENTER, leading=26)
    estilo_capa_sub    = ParagraphStyle("cap_s", fontName=FR, fontSize=14, textColor=C_BLUE_LIGHT,
                                        alignment=TA_CENTER, leading=18)
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=15 * mm,  bottomMargin=15 * mm,
    )

    flowables = []

    # ── Capa ──────────────────────────────────────────
    flowables.append(Spacer(1, 40 * mm))
    tbl_capa = Table(
        [[Paragraph(produto_nome, estilo_capa_titulo)]],
        colWidths=[W - 30 * mm],
    )
    tbl_capa.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8 * mm),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8 * mm),
    ]))
    flowables.append(tbl_capa)
    flowables.append(Spacer(1, 8 * mm))
    nivel_label = {"facil": "Fácil", "medio": "Médio", "dificil": "Difícil", "gigante": "Gigante"}.get(dificuldade, "")
    tema_label  = tema.replace("_", " ").title()
    flowables.append(Paragraph(f"{len(puzzles)} Puzzles · Nível {nivel_label} · Tema: {tema_label}", estilo_capa_sub))
    flowables.append(Spacer(1, 6 * mm))
    flowables.append(Paragraph("CogniVita — Estimulação Cognitiva para Idosos", estilo_capa_sub))
    flowables.append(PageBreak())

    # ── Puzzles ───────────────────────────────────────
    for i, puzzle in enumerate(puzzles, start=1):
        flowables.extend(_pagina_puzzle(puzzle, i, produto_nome, dificuldade))

    # ── Gabaritos (4 por página) ──────────────────────
    flowables.append(Paragraph("GABARITO", ParagraphStyle("gt", fontName=FB, fontSize=16,
                                                           textColor=C_BLUE, alignment=TA_CENTER)))
    flowables.append(Spacer(1, 4 * mm))

    estilo_gab_label = ParagraphStyle("gab", fontName=FB, fontSize=9, textColor=C_DARK,
                                      alignment=TA_CENTER, leading=11)
    for i in range(0, len(puzzles), 4):
        lote = puzzles[i:i + 4]
        for j in range(0, len(lote), 2):
            cel_a = [Paragraph(f"#{i+j+1}", estilo_gab_label),
                     _renderizar_grid(lote[j]["grid"], lote[j]["gabarito"], escala=0.42)]
            if j + 1 < len(lote):
                cel_b = [Paragraph(f"#{i+j+2}", estilo_gab_label),
                         _renderizar_grid(lote[j+1]["grid"], lote[j+1]["gabarito"], escala=0.42)]
            else:
                cel_b = [Paragraph("", estilo_gab_label), Spacer(1, 1)]
            tbl_gab = Table([[cel_a, cel_b]], colWidths=[(W - 30 * mm) / 2] * 2)
            tbl_gab.setStyle(TableStyle([
                ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            flowables.append(tbl_gab)
            flowables.append(Spacer(1, 4 * mm))
        if i + 4 < len(puzzles):
            flowables.append(PageBreak())

    doc.build(flowables)
    return str(pdf_path.resolve())
