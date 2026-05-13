"""
generator/pdf.py
Cognivita — geração de PDF para apostilas físicas com ReportLab.

Função principal:
  gerar_pdf(apostila_id, topico, conteudo_json) -> str  (caminho absoluto do PDF)
"""

import json
import os
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white, lightgrey
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    KeepTogether,
)
from reportlab.platypus.flowables import HRFlowable
from reportlab.pdfgen import canvas as pdfgen_canvas

# ---------------------------------------------------------------------------
# Constantes de cores e fontes
# ---------------------------------------------------------------------------

COLOR_GREEN = HexColor("#1B6B4A")
COLOR_LIGHT_GREEN = HexColor("#D4EDE3")
COLOR_HEADER_BG = HexColor("#F5F5F0")
COLOR_PAGE_BG = white
COLOR_TEXT = HexColor("#1A1A1A")
COLOR_SUBTEXT = HexColor("#555555")
COLOR_LINE = HexColor("#CCCCCC")

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_OBLIQUE = "Helvetica-Oblique"

# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------

def _build_styles():
    base = getSampleStyleSheet()

    styles = {}

    styles["cover_logo"] = ParagraphStyle(
        "cover_logo",
        fontName=FONT_BOLD,
        fontSize=36,
        textColor=COLOR_GREEN,
        alignment=TA_CENTER,
        spaceAfter=8 * mm,
        leading=42,
    )

    styles["cover_title"] = ParagraphStyle(
        "cover_title",
        fontName=FONT_BOLD,
        fontSize=28,
        textColor=COLOR_TEXT,
        alignment=TA_CENTER,
        spaceAfter=6 * mm,
        leading=34,
    )

    styles["cover_subtitle"] = ParagraphStyle(
        "cover_subtitle",
        fontName=FONT_REGULAR,
        fontSize=18,
        textColor=COLOR_SUBTEXT,
        alignment=TA_CENTER,
        spaceAfter=4 * mm,
        leading=24,
    )

    styles["cover_footer"] = ParagraphStyle(
        "cover_footer",
        fontName=FONT_OBLIQUE,
        fontSize=13,
        textColor=COLOR_SUBTEXT,
        alignment=TA_CENTER,
        leading=18,
    )

    styles["exercise_header"] = ParagraphStyle(
        "exercise_header",
        fontName=FONT_BOLD,
        fontSize=14,
        textColor=white,
        alignment=TA_LEFT,
        leading=20,
        leftIndent=4 * mm,
    )

    styles["body_text"] = ParagraphStyle(
        "body_text",
        fontName=FONT_REGULAR,
        fontSize=13,
        textColor=COLOR_TEXT,
        alignment=TA_JUSTIFY,
        spaceAfter=3 * mm,
        leading=20,
    )

    styles["instruction_label"] = ParagraphStyle(
        "instruction_label",
        fontName=FONT_BOLD,
        fontSize=12,
        textColor=COLOR_GREEN,
        spaceAfter=1 * mm,
        leading=17,
    )

    styles["instruction_item"] = ParagraphStyle(
        "instruction_item",
        fontName=FONT_REGULAR,
        fontSize=13,
        textColor=COLOR_TEXT,
        leftIndent=6 * mm,
        spaceAfter=2 * mm,
        leading=20,
    )

    styles["answer_label"] = ParagraphStyle(
        "answer_label",
        fontName=FONT_BOLD,
        fontSize=12,
        textColor=COLOR_GREEN,
        spaceAfter=2 * mm,
        leading=17,
    )

    return styles


# ---------------------------------------------------------------------------
# Numeração de páginas (canvas callback)
# ---------------------------------------------------------------------------

class _PageNumberCanvas(pdfgen_canvas.Canvas):
    """Canvas que desenha o número de página no rodapé de cada página."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(num_pages)
            super().showPage()
        super().save()

    def _draw_page_number(self, page_count):
        page = self._pageNumber
        # Não numerar capa
        if page <= 1:
            return
        self.saveState()
        self.setFont(FONT_REGULAR, 10)
        self.setFillColor(COLOR_SUBTEXT)
        text = f"Página {page} de {page_count}"
        self.drawCentredString(A4[0] / 2, 12 * mm, text)
        self.restoreState()


# ---------------------------------------------------------------------------
# Flowables auxiliares
# ---------------------------------------------------------------------------

def _exercise_header_flowable(numero: int, titulo: str) -> Table:
    """Retorna uma tabela-cabeçalho colorida para o exercício."""
    styles = _build_styles()
    label = f"EXERCÍCIO {numero} — {titulo.upper()}"
    para = Paragraph(label, styles["exercise_header"])
    tbl = Table([[para]], colWidths=[A4[0] - 40 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_GREEN),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [COLOR_GREEN]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOX", (0, 0), (-1, -1), 0, COLOR_GREEN),
    ]))
    return tbl


def _answer_lines(n: int = 8):
    """Retorna flowables com n linhas de escrita."""
    items = []
    for _ in range(n):
        items.append(HRFlowable(
            width="100%",
            thickness=0.75,
            color=COLOR_LINE,
            spaceAfter=7 * mm,
        ))
    return items


def _answer_box():
    """Retorna um flowable com um quadrado para resposta."""
    data = [[""]]
    tbl = Table(data, colWidths=[14 * cm], rowHeights=[5 * cm])
    tbl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, HexColor("#999999")),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#FAFAF8")),
    ]))
    return tbl


def _answer_bullets(n: int = 5):
    """Retorna flowables com n linhas de bullet para lista."""
    items = []
    for _ in range(n):
        row = Table(
            [["•  _______________________________________________"]],
            colWidths=[A4[0] - 40 * mm],
        )
        row.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
            ("FONTSIZE", (0, 0), (-1, -1), 13),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ]))
        items.append(row)
        items.append(Spacer(1, 4 * mm))
    return items


# ---------------------------------------------------------------------------
# Montagem da capa
# ---------------------------------------------------------------------------

def _cover_band(label: str, bg_color=None, text_color=white, font_size=13) -> Table:
    """Retorna uma faixa colorida de largura total para a capa."""
    if bg_color is None:
        bg_color = COLOR_GREEN
    style = ParagraphStyle(
        "_band",
        fontName=FONT_BOLD,
        fontSize=font_size,
        textColor=text_color,
        alignment=TA_CENTER,
        leading=font_size + 4,
    )
    para = Paragraph(label, style)
    tbl = Table([[para]], colWidths=[A4[0] - 40 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_color),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return tbl


def _build_cover(topico: dict, num_exercicios: int) -> list:
    styles = _build_styles()
    nome_topico = topico.get("nome", topico.get("name", str(topico)))

    story = []

    # Faixa superior verde escuro com o nome da marca
    story.append(_cover_band("COGNIVITA", bg_color=COLOR_GREEN, text_color=white, font_size=18))
    story.append(Spacer(1, 25 * mm))

    # Logo COGNIVITA grande
    story.append(Paragraph("COGNIVITA", styles["cover_logo"]))

    # Linha decorativa
    story.append(HRFlowable(
        width="60%",
        thickness=2,
        color=COLOR_GREEN,
        spaceAfter=10 * mm,
        hAlign="CENTER",
    ))

    story.append(Spacer(1, 10 * mm))

    # Título da apostila
    story.append(Paragraph(f"Apostila de {nome_topico}", styles["cover_title"]))

    story.append(Spacer(1, 8 * mm))

    # Subtítulo
    story.append(Paragraph(
        f"Para Idosos 60+ | {num_exercicios} Exercícios",
        styles["cover_subtitle"],
    ))

    story.append(Spacer(1, 35 * mm))

    # Faixa de rodapé verde claro
    story.append(_cover_band(
        "Material Físico | Impresso e Encadernado",
        bg_color=COLOR_HEADER_BG,
        text_color=COLOR_GREEN,
        font_size=13,
    ))

    story.append(Spacer(1, 4 * mm))

    # Footer pequeno com domínio
    story.append(Paragraph("cognivita.com.br", styles["cover_footer"]))

    story.append(PageBreak())

    # --- Página 2: instruções de uso ---
    story.extend(_build_instructions_page(nome_topico, num_exercicios))

    return story


def _build_instructions_page(nome_topico: str, num_exercicios: int) -> list:
    """Página de instruções de uso antes dos exercícios."""
    styles = _build_styles()
    items = []

    items.append(_cover_band("COMO USAR ESTA APOSTILA", bg_color=COLOR_GREEN, text_color=white, font_size=15))
    items.append(Spacer(1, 8 * mm))

    intro_style = ParagraphStyle(
        "_intro",
        fontName=FONT_REGULAR,
        fontSize=13,
        textColor=COLOR_TEXT,
        leading=22,
        spaceAfter=4 * mm,
        alignment=TA_JUSTIFY,
    )
    bold_intro = ParagraphStyle(
        "_bold_intro",
        fontName=FONT_BOLD,
        fontSize=13,
        textColor=COLOR_GREEN,
        leading=20,
        spaceAfter=3 * mm,
    )

    items.append(Paragraph(
        f"Esta apostila contém <b>{num_exercicios} exercícios</b> de estimulação cognitiva "
        f"para o tema <b>{nome_topico}</b>, desenvolvidos especialmente para pessoas acima de 60 anos.",
        intro_style,
    ))

    items.append(Spacer(1, 4 * mm))
    items.append(Paragraph("Dicas para aproveitar melhor:", bold_intro))

    dicas = [
        "Faça os exercícios no seu próprio ritmo — não há pressa.",
        "Use caneta ou lápis com ponta grossa para escrever com mais conforto.",
        "Se precisar de ajuda, peça a um familiar ou cuidador.",
        "Tente fazer pelo menos 2 exercícios por dia para manter a rotina.",
        "Não existe resposta errada — o importante é exercitar o cérebro.",
        "Parabéns por cuidar da sua saúde cognitiva!",
    ]
    for dica in dicas:
        items.append(Paragraph(f"• {dica}", intro_style))

    items.append(Spacer(1, 6 * mm))
    items.append(HRFlowable(width="100%", thickness=0.5, color=COLOR_LINE, spaceAfter=6 * mm))

    items.append(Paragraph(
        "Este material foi produzido pela equipe Cognivita com base em técnicas de "
        "estimulação cognitiva recomendadas por terapeutas ocupacionais e especialistas "
        "em saúde do idoso.",
        intro_style,
    ))

    items.append(PageBreak())
    return items


# ---------------------------------------------------------------------------
# Montagem dos exercícios
# ---------------------------------------------------------------------------

def _build_exercise(exercicio: dict) -> list:
    """Retorna lista de flowables para um único exercício."""
    styles = _build_styles()

    numero = exercicio.get("numero", "?")
    titulo = exercicio.get("titulo", "")
    descricao = exercicio.get("descricao", "")
    instrucoes = exercicio.get("instrucoes", [])
    espaco = exercicio.get("espaco_resposta", "linha")

    items = []

    # Cabeçalho colorido
    items.append(_exercise_header_flowable(numero, titulo))
    items.append(Spacer(1, 4 * mm))

    # Descrição
    if descricao:
        items.append(Paragraph(descricao, styles["body_text"]))
        items.append(Spacer(1, 3 * mm))

    # Instruções
    if instrucoes:
        items.append(Paragraph("Como fazer:", styles["instruction_label"]))
        for i, passo in enumerate(instrucoes, 1):
            items.append(Paragraph(f"{i}. {passo}", styles["instruction_item"]))
        items.append(Spacer(1, 4 * mm))

    # Espaço de resposta
    items.append(Paragraph("Sua resposta:", styles["answer_label"]))

    if espaco == "quadrado":
        items.append(_answer_box())
        items.append(Spacer(1, 4 * mm))
    elif espaco == "lista":
        items.extend(_answer_bullets(5))
    else:  # "linha" (padrão)
        items.extend(_answer_lines(8))

    return items


def _build_exercises_pages(exercicios: list) -> list:
    """Agrupa exercícios em páginas (2 por página), retorna flowables."""
    story = []
    styles = _build_styles()

    i = 0
    while i < len(exercicios):
        page_items = []

        # Primeiro exercício da página
        ex1_items = _build_exercise(exercicios[i])
        page_items.extend(ex1_items)

        # Separador entre exercícios na mesma página
        if i + 1 < len(exercicios):
            page_items.append(Spacer(1, 6 * mm))
            page_items.append(HRFlowable(
                width="100%",
                thickness=0.5,
                color=COLOR_LIGHT_GREEN,
                spaceAfter=6 * mm,
            ))

            # Segundo exercício da página
            ex2_items = _build_exercise(exercicios[i + 1])
            page_items.extend(ex2_items)

        # Tenta manter os dois exercícios juntos; se não couber, coloca em páginas separadas
        story.append(KeepTogether(page_items))
        story.append(PageBreak())

        i += 2

    return story


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def gerar_pdf(apostila_id: int, topico: dict, conteudo_json: str) -> str:
    """
    Gera PDF da apostila e salva em output/pdfs/apostila_{apostila_id}.pdf.

    Args:
        apostila_id: ID único da apostila (usado no nome do arquivo).
        topico: dict com pelo menos {"nome": str}.
        conteudo_json: JSON string produzida por generator.content.gerar_conteudo().

    Returns:
        Caminho absoluto para o arquivo PDF gerado.
    """
    # --- Parseia conteúdo ---
    conteudo = json.loads(conteudo_json)
    exercicios = conteudo.get("exercicios", [])
    num_exercicios = conteudo.get("num_exercicios", len(exercicios))

    # --- Garante diretório de saída ---
    base_dir = Path(__file__).parent.parent  # raiz do projeto
    output_dir = base_dir / "output" / "pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / f"apostila_{apostila_id}.pdf"

    # --- Configura documento ---
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title=f"Apostila de {topico.get('nome', '')} — Cognivita",
        author="Cognivita",
        subject=f"Apostila para idosos 60+ | {num_exercicios} exercícios",
    )

    # --- Monta story ---
    story = []
    story.extend(_build_cover(topico, num_exercicios))
    story.extend(_build_exercises_pages(exercicios))

    # --- Gera PDF com numeração de páginas ---
    doc.build(story, canvasmaker=_PageNumberCanvas)

    return str(pdf_path.resolve())


# ---------------------------------------------------------------------------
# Bloco __main__ — teste rápido sem API
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    _topico = {"id": 1, "nome": "Memória", "slug": "memoria"}
    _exercicios = [
        {
            "numero": i,
            "titulo": f"Exercício {i}",
            "descricao": "Descrição detalhada do exercício para estimulação cognitiva.",
            "instrucoes": ["Passo 1: leia com atenção", "Passo 2: escreva a resposta"],
            "espaco_resposta": ["linha", "quadrado", "lista"][i % 3],
        }
        for i in range(1, 7)
    ]
    _conteudo = _json.dumps(
        {"topico": "Memoria", "num_exercicios": 6, "exercicios": _exercicios},
        ensure_ascii=False,
    )
    _path = gerar_pdf(apostila_id=0, topico=_topico, conteudo_json=_conteudo)
    print("PDF gerado em:", _path)
    print("Existe:", os.path.exists(_path), "| Tamanho:", os.path.getsize(_path), "bytes")
