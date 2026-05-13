"""
generator/images.py
Cognivita — geração de capas de apostilas com Pillow.

Funções:
  gerar_capas(apostila_id, topico, num_exercicios, variacao) -> list[str]
  gerar_capas_kit(kit_id, kit_nome, apostilas, variacao)     -> list[str]
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SIZE = (1200, 1200)

# Paletas: (cor_escura, cor_clara)
PALETAS = {
    1: ("#1B6B4A", "#F5F5F0"),
    2: ("#1A4B6B", "#F0F5FF"),
    3: ("#4B1B6B", "#F5F0FF"),
    4: ("#8B3A0F", "#FFF5F0"),
    5: ("#6B1B1B", "#FFF0F0"),
    6: ("#0D4A2E", "#F0FFF5"),
}

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "images"


# ---------------------------------------------------------------------------
# Helpers de cor e fonte
# ---------------------------------------------------------------------------

def _hex(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _font(size: int):
    """Tenta arial.ttf (Windows), cai para o default do PIL."""
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _font_regular(size: int):
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    """Retorna (width, height) compatível com PIL antigo e novo."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        return draw.textsize(text, font=font)


def _centered_text(draw, y, text, font, fill, width=1200):
    tw, th = _text_size(draw, text, font)
    x = (width - tw) // 2
    draw.text((x, y), text, font=font, fill=fill)
    return th


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Quebra texto em linhas respeitando max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        w, _ = _text_size(draw, test, font)
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


# ---------------------------------------------------------------------------
# Acentos visuais por variação
# ---------------------------------------------------------------------------

def _draw_accent(draw: ImageDraw.ImageDraw, variacao: int, cor_escura: tuple):
    if variacao == 1:
        pass  # Sem acento

    elif variacao == 2:
        # Barra superior
        draw.rectangle([(0, 0), (1200, 14)], fill=cor_escura)

    elif variacao == 3:
        # Barra lateral esquerda
        draw.rectangle([(0, 0), (14, 1200)], fill=cor_escura)

    elif variacao == 4:
        # Canto arredondado accent — retângulo no canto superior direito
        draw.rectangle([(950, 0), (1200, 120)], fill=cor_escura)

    elif variacao == 5:
        # Dois acentos: barra superior + barra inferior fina
        draw.rectangle([(0, 0), (1200, 10)], fill=cor_escura)
        draw.rectangle([(0, 840), (1200, 848)], fill=cor_escura)

    elif variacao == 6:
        # Diagonal accent — triângulo no canto superior esquerdo
        draw.polygon([(0, 0), (220, 0), (0, 220)], fill=cor_escura)


# ---------------------------------------------------------------------------
# Geração de uma capa individual
# ---------------------------------------------------------------------------

def _gerar_capa(
    path: Path,
    variacao: int,
    titulo: str,
    subtitulo: str,
    badge_texto: str,
    rodape_linha1: str,
    rodape_linha2: str,
):
    cor_escura_hex, cor_clara_hex = PALETAS[variacao]
    cor_escura = _hex(cor_escura_hex)
    cor_clara = _hex(cor_clara_hex)
    branco = (255, 255, 255)

    img = Image.new("RGB", SIZE, color=cor_clara)
    draw = ImageDraw.Draw(img)

    # Acentos visuais
    _draw_accent(draw, variacao, cor_escura)

    # --- Logo COGNIVITA (topo) ---
    font_logo = _font(38)
    logo_y = 55
    _centered_text(draw, logo_y, "COGNIVITA", font_logo, cor_escura)

    # Linha decorativa abaixo do logo
    lx = 480
    draw.rectangle([(lx, logo_y + 52), (1200 - lx, logo_y + 55)], fill=cor_escura)

    # --- Título ---
    font_titulo = _font(90)
    font_titulo_med = _font(74)
    font_titulo_sm = _font(60)

    title_max_w = 1000
    lines = _wrap_text(titulo.upper(), font_titulo, title_max_w, draw)
    if len(lines) > 2:
        lines = _wrap_text(titulo.upper(), font_titulo_med, title_max_w, draw)
    if len(lines) > 3:
        lines = _wrap_text(titulo.upper(), font_titulo_sm, title_max_w, draw)

    titulo_y_start = 200
    line_gap = 10
    total_h = sum(_text_size(draw, l, font_titulo)[1] + line_gap for l in lines)
    y = titulo_y_start
    for line in lines:
        h = _centered_text(draw, y, line, font_titulo, cor_escura)
        y += h + line_gap

    # --- Subtítulo ---
    font_sub = _font_regular(44)
    sub_y = max(y + 30, 520)
    _centered_text(draw, sub_y, subtitulo, font_sub, cor_escura)

    # --- Badge de exercícios ---
    font_badge = _font(48)
    badge_w, badge_h = _text_size(draw, badge_texto, font_badge)
    pad_x, pad_y = 50, 18
    bx = (1200 - badge_w - pad_x * 2) // 2
    by = sub_y + 90
    draw.rounded_rectangle(
        [(bx, by), (bx + badge_w + pad_x * 2, by + badge_h + pad_y * 2)],
        radius=40,
        fill=cor_escura,
    )
    draw.text((bx + pad_x, by + pad_y), badge_texto, font=font_badge, fill=branco)

    # --- Rodapé ---
    footer_h = 155
    footer_y = 1200 - footer_h
    draw.rectangle([(0, footer_y), (1200, 1200)], fill=cor_escura)

    font_footer1 = _font(46)
    font_footer2 = _font_regular(34)

    f1_y = footer_y + 28
    _centered_text(draw, f1_y, rodape_linha1, font_footer1, branco)

    f1_h = _text_size(draw, rodape_linha1, font_footer1)[1]
    _centered_text(draw, f1_y + f1_h + 10, rodape_linha2, font_footer2, branco)

    img.save(str(path), "PNG")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def gerar_capas(
    apostila_id: int,
    topico: dict,
    num_exercicios: int,
    variacao: int = None,
) -> list[str]:
    """
    Gera capas para uma apostila individual.

    Retorna lista de caminhos de arquivos PNG gerados.
    Se `variacao` for especificado, gera apenas aquela variação (1–6).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    titulo = topico.get("nome", "Exercícios")
    badge = f"✦ {num_exercicios} EXERCÍCIOS ✦"
    subtitulo = "Para Idosos 60+"
    rodape1 = "APOSTILA FÍSICA"
    rodape2 = "Impressa e Encadernada"

    variacoes = [variacao] if variacao is not None else list(range(1, 7))
    paths = []

    for v in variacoes:
        fname = OUTPUT_DIR / f"apostila_{apostila_id}_v{v}.png"
        _gerar_capa(fname, v, titulo, subtitulo, badge, rodape1, rodape2)
        paths.append(str(fname))

    return paths


def gerar_capas_kit(
    kit_id: int,
    kit_nome: str,
    apostilas: list[dict],
    variacao: int = None,
) -> list[str]:
    """
    Gera capas para um kit de apostilas.

    `apostilas` é uma lista de dicts com pelo menos {'num_exercicios': int}.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total_exercicios = sum(a.get("num_exercicios", 0) for a in apostilas)
    badge = f"✦ {total_exercicios} EXERCÍCIOS ✦"
    subtitulo = "Para Idosos 60+"
    rodape1 = "KIT 2 EM 1"
    rodape2 = "Apostilas Físicas"

    variacoes = [variacao] if variacao is not None else list(range(1, 7))
    paths = []

    for v in variacoes:
        fname = OUTPUT_DIR / f"kit_{kit_id}_v{v}.png"
        _gerar_capa(fname, v, kit_nome, subtitulo, badge, rodape1, rodape2)
        paths.append(str(fname))

    return paths
