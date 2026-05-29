"""
generator/images.py
Cognivita — geração de capas profissionais com Pillow.

Layout: header de marca / mockup do livro com sombra e lombada / chips de benefício / rodapé
6 variações de cor; 3 estilos de layout (A: centrado, B: split, C: book à direita).

Funções públicas:
  gerar_capas(apostila_id, topico, num_exercicios, variacao) -> list[str]
  gerar_capas_kit(kit_id, kit_nome, apostilas, variacao)     -> list[str]
"""

import logging
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_SUBTITULOS = {
    "coordenação motora":       "Movimento com propósito, vida com mais autonomia",
    "coordenação motora fina":  "Precisão e leveza para o dia a dia independente",
    "memória":                  "Exercícios para lembrar o que importa",
    "atenção e concentração":   "Foco renovado para aproveitar cada momento",
    "percepção visual":         "Veja o mundo com mais clareza e confiança",
    "sequência lógica":         "Raciocínio afiado, decisões mais seguras",
}

def _to_roman(n: int) -> str:
    vals = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
            (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
    result = ""
    for v, s in vals:
        while n >= v:
            result += s
            n -= v
    return result


def _subtitulo(titulo: str) -> str:
    chave = titulo.lower().strip()
    for k, v in _SUBTITULOS.items():
        if k in chave:
            return v
    return "Exercícios para uma mente ativa e feliz"


def _build_ai_prompts(titulo: str, num_exercicios: int = 60) -> dict:
    """Gera prompts orgânicos para Cognivita baseados no título e quantidade de exercícios."""
    sub = _subtitulo(titulo)
    ex  = f"{num_exercicios} EXERCÍCIOS"

    return {
        # v1 — Produto isolado: livro fechado em destaque, capa totalmente visível
        1: (
            f"Ultra professional e-commerce product photography, photorealistic 4k, organic warm editorial style. "
            f"Hero: one thick closed spiral-bound workbook standing upright centered on a light oak wooden surface, cover fully sharp and in focus. "
            f"Cover design: warm cream background with subtle watercolor organic shapes in dark forest green (#1B6B4A) at top and bottom edges. "
            f"Top of cover: small illustrated brain with leaf sprout icon, brand name spelled exactly COGNIVITA (C-O-G-N-I-V-I-T-A, not cognitiva) in bold dark green capital letters. "
            f"Center of cover: large bold title \"{titulo}\" in dark forest green, strong typographic hierarchy. "
            f"Below title: italic text \"{sub}\" in sage green. "
            f"Bottom of cover: rounded pill badge in forest green with white bold text \"{ex}\". "
            f"Warm gold spiral binding on left side, thick pages visible on right side showing book depth. "
            f"Table surface: warm natural linen. Side props: small eucalyptus sprig, reading glasses with thin gold frame, ceramic mug of tea, mini potted succulent. "
            f"Soft diffused natural studio light from upper left, gentle warm shadow on right, airy premium editorial mood, ultra sharp cover detail."
        ),
        # v2 — Lifestyle: idosa usando o caderno, livro fechado ao lado com capa visível
        2: (
            f"Warm authentic lifestyle photo for Brazilian e-commerce, photorealistic 4k, golden hour natural light. "
            f"Elderly Brazilian woman 70s, short white curly hair, reading glasses, soft beige cardigan, "
            f"sitting at a light wooden table near a large window, smiling warmly, writing with a pen in a large open spiral workbook "
            f"showing cognitive exercise pages with word searches and number grids printed in large clear font for seniors. "
            f"Standing upright beside her on the table: a closed spiral-bound workbook facing the camera, cover fully visible and sharp. "
            f"Cover design: warm cream background with organic watercolor green shapes at edges, "
            f"brand name spelled exactly COGNIVITA (C-O-G-N-I-V-I-T-A, not cognitiva) in bold dark green at top, large centered title \"{titulo}\" in dark forest green, "
            f"italic subtitle \"{sub}\" below, rounded badge reading \"{ex}\" at bottom. Gold spiral binding on left. "
            f"Ceramic mug of tea, small green plant in soft-focus background, warm golden window light streaming in. "
            f"Authentic heartwarming expression, shallow depth of field, cinematic warm mood."
        ),
        # v3 — Flat lay: caderno aberto visto de cima com exercícios visíveis e props
        3: (
            f"Professional overhead flat lay photography for Brazilian e-commerce, photorealistic 4k, warm organic aesthetic. "
            f"Center: large open spiral-bound workbook showing two pages of cognitive exercises — word searches, number sequences and memory grids printed in large clear font for seniors, pages bright white and sharp. "
            f"Propped upright against the open workbook: one closed spiral-bound workbook with cover fully visible. "
            f"Cover design: warm cream background with organic watercolor green shapes, "
            f"brand name spelled exactly COGNIVITA (C-O-G-N-I-V-I-T-A, not cognitiva) in bold dark green at top, large title \"{titulo}\" centered in dark forest green, "
            f"italic subtitle \"{sub}\" below, rounded badge \"{ex}\" at bottom. Gold spiral binding on left. "
            f"Props arranged organically around the books on warm linen surface: two yellow pencils, gold paper clips, "
            f"a ceramic coffee mug, pressed dried eucalyptus leaves, reading glasses with thin gold frame, small succulent plant. "
            f"Soft diffused natural light from above, no harsh shadows, clean airy composition, ultra sharp detail on both books."
        ),
    }

# Estimated book cover rect (x0, y0, x1, y1) within the 1200x1200 composited image.
# Region sits between the header (ends y=106) and bottom panel (starts y=870).
# v2 (lifestyle) is None — book too small/angled to reliably composite.
_COVER_LABEL_COORDS = {
    1: (380, 130, 760, 820),  # product shot: recuado da espiral, cobre a capa branca
    3: (260, 115, 740, 820),  # flat lay: book fills center of image
}

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SIZE = (1200, 1200)

# Paletas: (escuro, claro, acento)
PALETAS = {
    1: ("#1B6B4A", "#F0FAF5", "#FFFFFF"),   # verde floresta
    2: ("#1A4B6B", "#EFF6FF", "#FFFFFF"),   # azul profundo
    3: ("#4B1B6B", "#F5F0FF", "#FFFFFF"),   # roxo
    4: ("#7A3010", "#FFF5F0", "#FFFFFF"),   # terracota
    5: ("#2D4A1E", "#F2FAF0", "#FFFFFF"),   # verde musgo
    6: ("#1C3A5C", "#EBF4FF", "#D4AC56"),   # azul naval + dourado
}

# Benefícios genéricos por posição (usados nos chips)
_BENEFICIOS_PADRAO = [
    "Estimula o Cérebro",
    "Fonte Ampliada",
    "Apostila A4 Impressa",
]

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "images"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _hex(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _blend(c1: tuple, c2: tuple, t: float) -> tuple:
    """Interpolação linear entre duas cores RGB."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _font(size: int):
    for name in ("arialbd.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"):
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
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except AttributeError:
        return draw.textsize(text, font=font)


def _centered_x(draw, y, text, font, fill, canvas_w=1200):
    tw, _ = _text_size(draw, text, font)
    draw.text(((canvas_w - tw) // 2, y), text, font=font, fill=fill)


def _wrap(text: str, font, max_w: int, draw) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if _text_size(draw, test, font)[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


# ---------------------------------------------------------------------------
# Cover label helpers (composited on AI photo book cover area)
# ---------------------------------------------------------------------------

def _render_cover_label(titulo: str, cor_escura: tuple, cor_acento: tuple,
                         width: int, height: int) -> Image.Image:
    """Renders a branded book cover label (RGBA) to be pasted on the AI photo."""
    label = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ld = ImageDraw.Draw(label)

    strip_h = max(36, int(height * 0.13))
    ld.rectangle([(0, 0), (width, strip_h)], fill=(*cor_escura, 230))
    font_brand = _font(max(16, strip_h - 14))
    bw, bh = _text_size(ld, "COGNIVITA", font_brand)
    ld.text(((width - bw) // 2, (strip_h - bh) // 2),
            "COGNIVITA", font=font_brand, fill=(*cor_acento, 255))

    bot_h = max(28, int(height * 0.10))
    mid_y0 = strip_h
    mid_y1 = height - bot_h
    ld.rectangle([(0, mid_y0), (width, mid_y1)], fill=(255, 255, 255, 220))

    pad = 18
    avail_w = width - pad * 2
    font_sz = max(24, min(54, int(avail_w / max(len(titulo), 1) * 2.0)))
    font_t = _font(font_sz)
    lines = _wrap(titulo.upper(), font_t, avail_w, ld)
    if len(lines) > 3:
        font_t = _font(max(20, font_sz - 12))
        lines = _wrap(titulo.upper(), font_t, avail_w, ld)

    total_th = sum(_text_size(ld, ln, font_t)[1] + 4 for ln in lines)
    ty = mid_y0 + ((mid_y1 - mid_y0) - total_th) // 2
    for ln in lines:
        lw, lh = _text_size(ld, ln, font_t)
        ld.text(((width - lw) // 2, ty), ln, font=font_t, fill=(*cor_escura, 245))
        ty += lh + 4

    ld.rectangle([(0, mid_y1), (width, height)], fill=(*cor_escura, 195))
    bot_text = "APOSTILA FÍSICA"
    # Start at bot_h-10 and shrink until text fits
    sz = max(12, bot_h - 10)
    font_bot = _font_regular(sz)
    bw2, bh2 = _text_size(ld, bot_text, font_bot)
    while bw2 > width - 12 and sz > 12:
        sz -= 2
        font_bot = _font_regular(sz)
        bw2, bh2 = _text_size(ld, bot_text, font_bot)
    ld.text(((width - bw2) // 2, mid_y1 + (bot_h - bh2) // 2),
            bot_text, font=font_bot, fill=(255, 255, 255, 210))

    return label


def _paste_cover_label(base: Image.Image, titulo: str,
                        cor_escura: tuple, cor_acento: tuple,
                        variacao: int) -> Image.Image:
    """Composites a branded cover label on the AI photo at the estimated book cover position."""
    coords = _COVER_LABEL_COORDS.get(variacao)
    if coords is None:
        return base
    x0, y0, x1, y1 = coords
    try:
        label = _render_cover_label(titulo, cor_escura, cor_acento, x1 - x0, y1 - y0)
        if base.mode != "RGBA":
            base = base.convert("RGBA")
        base.paste(label, (x0, y0), label)
    except Exception as e:
        logger.warning("Falha ao colar label na capa AI: %s", e)
    return base


# ---------------------------------------------------------------------------
# Componentes visuais reutilizáveis
# ---------------------------------------------------------------------------

def _draw_header(draw: ImageDraw.ImageDraw, cor_escura: tuple, cor_acento: tuple,
                 h: int = 88):
    """Faixa superior com nome da marca."""
    draw.rectangle([(0, 0), (1200, h)], fill=cor_escura)

    font_logo = _font(40)
    logo_text = "COGNIVITA"
    tw, _ = _text_size(draw, logo_text, font_logo)
    draw.text(((1200 - tw) // 2, (h - 44) // 2), logo_text, font=font_logo, fill=cor_acento)

    # Linha fina de acento abaixo do header
    draw.rectangle([(0, h), (1200, h + 4)], fill=_blend(cor_escura, (255, 255, 255), 0.4))


def _draw_footer(draw: ImageDraw.ImageDraw, cor_escura: tuple, cor_acento: tuple,
                 linha1: str, linha2: str, y0: int = 1040):
    """Rodapé escuro com duas linhas de texto."""
    draw.rectangle([(0, y0), (1200, 1200)], fill=cor_escura)
    # Linha decorativa no topo do rodapé
    draw.rectangle([(0, y0), (1200, y0 + 4)], fill=_blend(cor_escura, (255, 255, 255), 0.35))

    font_f1 = _font(44)
    font_f2 = _font_regular(32)
    branco = (255, 255, 255)

    tw1, th1 = _text_size(draw, linha1, font_f1)
    tw2, _ = _text_size(draw, linha2, font_f2)
    total = th1 + 10 + 36
    y = y0 + ((1200 - y0) - total) // 2

    draw.text(((1200 - tw1) // 2, y), linha1, font=font_f1, fill=cor_acento)
    draw.text(((1200 - tw2) // 2, y + th1 + 10), linha2, font=font_f2, fill=branco)


def _draw_book_mockup(draw: ImageDraw.ImageDraw, img: Image.Image,
                      x0: int, y0: int, x1: int, y1: int,
                      cor_escura: tuple, cor_clara: tuple,
                      titulo_livro: str, subtitulo_livro: str):
    """
    Desenha um mockup 3D de livro físico dentro do retângulo (x0,y0)-(x1,y1).
    Sombra + lombada + capa com conteúdo.
    """
    spine_w = 36
    shadow_off = 14
    branco = (255, 255, 255)
    cinza_leve = _blend(cor_escura, (255, 255, 255), 0.85)
    cinza_medio = _blend(cor_escura, (255, 255, 255), 0.6)

    bw = x1 - x0
    bh = y1 - y0

    # Sombra
    draw.rectangle(
        [(x0 + shadow_off, y0 + shadow_off), (x1 + shadow_off, y1 + shadow_off)],
        fill=_blend(cor_escura, (255, 255, 255), 0.65)
    )

    # Páginas empilhadas (borda direita e inferior — efeito de espessura)
    page_depth = 10
    for i in range(page_depth, 0, -1):
        t = i / page_depth
        pg_col = _blend((240, 240, 235), (255, 255, 255), t)
        draw.rectangle(
            [(x0 + spine_w + i, y0 + i), (x1 + i, y1 + i)],
            fill=pg_col
        )

    # Lombada (spine)
    draw.rectangle([(x0, y0), (x0 + spine_w, y1)], fill=cor_escura)

    # Capa principal (branca)
    draw.rectangle([(x0 + spine_w, y0), (x1, y1)], fill=branco)

    # Borda da capa
    draw.rectangle([(x0 + spine_w, y0), (x1, y1)], outline=cinza_medio, width=2)

    # Margem interna decorativa
    margin = 24
    cx0 = x0 + spine_w + margin
    cx1 = x1 - margin
    cy0 = y0 + margin
    cy1 = y1 - margin
    draw.rectangle([(cx0, cy0), (cx1, cy1)], outline=cinza_leve, width=1)

    # Faixa colorida no topo da capa
    stripe_h = max(int(bh * 0.13), 40)
    draw.rectangle([(x0 + spine_w, y0), (x1, y0 + stripe_h)], fill=cor_escura)

    # "COGNIVITA" pequeno na faixa
    font_brand_small = _font(22)
    bst, _ = _text_size(draw, "COGNIVITA", font_brand_small)
    cover_w = x1 - (x0 + spine_w)
    draw.text(
        (x0 + spine_w + (cover_w - bst) // 2, y0 + (stripe_h - 26) // 2),
        "COGNIVITA", font=font_brand_small, fill=(255, 255, 255)
    )

    # Linhas decorativas (simulam linhas de caderno)
    line_y = y0 + stripe_h + 28
    for _ in range(4):
        draw.rectangle([(cx0 + 10, line_y), (cx1 - 10, line_y + 2)], fill=cinza_leve)
        line_y += 18

    # Título do livro (dentro da capa)
    cover_area_w = cx1 - cx0
    title_font_sz = max(36, min(64, int(cover_area_w / max(len(titulo_livro), 1) * 1.7)))
    font_title = _font(title_font_sz)
    lines = _wrap(titulo_livro.upper(), font_title, cover_area_w - 16, draw)
    if len(lines) > 3:
        font_title = _font(max(30, title_font_sz - 14))
        lines = _wrap(titulo_livro.upper(), font_title, cover_area_w - 16, draw)

    total_th = sum(_text_size(draw, l, font_title)[1] + 6 for l in lines)
    ty = y0 + stripe_h + int(bh * 0.15)
    for line in lines:
        lw, lh = _text_size(draw, line, font_title)
        draw.text((x0 + spine_w + (cover_w - lw) // 2, ty), line, font=font_title, fill=cor_escura)
        ty += lh + 6

    # Subtítulo do livro
    if subtitulo_livro:
        font_sub_book = _font_regular(26)
        sbs, _ = _text_size(draw, subtitulo_livro, font_sub_book)
        draw.text(
            (x0 + spine_w + (cover_w - sbs) // 2, y1 - 70),
            subtitulo_livro, font=font_sub_book, fill=cinza_medio
        )

    # Texto na lombada (vertical)
    try:
        from PIL import ImageFont as _IF
        spine_text = titulo_livro.upper()[:16]
        font_spine = _font_regular(18)
        txt_img = Image.new("RGBA", (bh - 20, spine_w - 8), (0, 0, 0, 0))
        td = ImageDraw.Draw(txt_img)
        td.text((10, 4), spine_text, font=font_spine, fill=(255, 255, 255))
        rotated = txt_img.rotate(90, expand=True)
        sx = x0 + (spine_w - rotated.width) // 2
        sy = y0 + (bh - rotated.height) // 2
        if img.mode != "RGBA":
            img_rgba = img.convert("RGBA")
            img_rgba.paste(rotated, (sx, sy), rotated)
            img.paste(img_rgba.convert("RGB"))
        else:
            img.paste(rotated, (sx, sy), rotated)
    except Exception:
        pass


def _draw_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                text: str, cor_escura: tuple, cor_acento: tuple):
    """Desenha um badge arredondado centralizado em (cx, cy)."""
    font_b = _font(42)
    tw, th = _text_size(draw, text, font_b)
    pad_x, pad_y = 44, 16
    bx0 = cx - (tw + pad_x * 2) // 2
    by0 = cy - (th + pad_y * 2) // 2
    bx1 = bx0 + tw + pad_x * 2
    by1 = by0 + th + pad_y * 2
    draw.rounded_rectangle([(bx0, by0), (bx1, by1)], radius=38, fill=cor_escura)
    draw.text((bx0 + pad_x, by0 + pad_y), text, font=font_b, fill=cor_acento)


def _draw_benefit_chips(draw: ImageDraw.ImageDraw, beneficios: list[str],
                        y: int, cor_escura: tuple, cor_clara: tuple,
                        canvas_w: int = 1200):
    """Desenha chips de benefício lado a lado."""
    font_chip = _font_regular(28)
    chip_h = 56
    pad_x = 28
    total_w = 0
    widths = []
    for b in beneficios:
        w, _ = _text_size(draw, b, font_chip)
        widths.append(w + pad_x * 2)
        total_w += w + pad_x * 2

    gap = min(24, (canvas_w - 80 - total_w) // max(len(beneficios) - 1, 1))
    total_w += gap * (len(beneficios) - 1)
    x = (canvas_w - total_w) // 2

    for i, (b, w) in enumerate(zip(beneficios, widths)):
        col = _blend(cor_escura, (255, 255, 255), 0.88)
        draw.rounded_rectangle(
            [(x, y), (x + w, y + chip_h)],
            radius=28,
            fill=col,
            outline=_blend(cor_escura, (255, 255, 255), 0.65),
        )
        tw, th = _text_size(draw, b, font_chip)
        draw.text(
            (x + (w - tw) // 2, y + (chip_h - th) // 2),
            b, font=font_chip, fill=cor_escura
        )
        x += w + gap


# ---------------------------------------------------------------------------
# Geração de imagem via HF FLUX.1-schnell
# ---------------------------------------------------------------------------

def _fetch_leonardo_image(prompt: str) -> "Image.Image | None":
    import io, time, requests as _req
    token = os.environ.get("LEONARDO_API_KEY", "")
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = _req.post(
            "https://cloud.leonardo.ai/api/rest/v1/generations",
            headers=headers,
            json={
                "modelId": "de7d3faf-762f-48e0-b3b7-9d0ac3a3fcf3",  # Leonardo Phoenix 1.0
                "prompt": prompt,
                "negative_prompt": (
                    "blurry text, illegible text, misspelled words, garbled letters, "
                    "distorted typography, wrong spelling, jumbled characters, bad fonts"
                ),
                "width": 1024,
                "height": 1024,
                "num_images": 1,
                "guidance_scale": 7,
                "alchemy": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        generation_id = resp.json()["sdGenerationJob"]["generationId"]

        for _ in range(30):
            time.sleep(3)
            r = _req.get(
                f"https://cloud.leonardo.ai/api/rest/v1/generations/{generation_id}",
                headers=headers,
                timeout=15,
            )
            r.raise_for_status()
            data = r.json().get("generations_by_pk", {})
            if data.get("status") == "COMPLETE":
                url = data["generated_images"][0]["url"]
                img_data = _req.get(url, timeout=30).content
                return Image.open(io.BytesIO(img_data)).convert("RGB")

        logger.warning("Leonardo AI: timeout aguardando geração")
    except Exception as e:
        logger.warning("Falha ao buscar imagem Leonardo AI: %s", e)
    return None


def _fetch_ideogram_image(prompt: str) -> "Image.Image | None":
    import io, requests as _req
    api_key = os.environ.get("IDEOGRAM_API_KEY", "")
    if not api_key:
        return None
    try:
        resp = _req.post(
            "https://api.ideogram.ai/generate",
            headers={"Api-Key": api_key, "Content-Type": "application/json"},
            json={
                "image_request": {
                    "prompt": prompt,
                    "model": "V_2_TURBO",
                    "aspect_ratio": "ASPECT_1_1",
                    "magic_prompt_option": "OFF",
                }
            },
            timeout=60,
        )
        resp.raise_for_status()
        img_url = resp.json()["data"][0]["url"]
        img_data = _req.get(img_url, timeout=30).content
        return Image.open(io.BytesIO(img_data)).convert("RGB")
    except Exception as e:
        logger.warning("Falha ao gerar imagem Ideogram: %s", e)
    return None


def _fetch_replicate_image(prompt: str) -> "Image.Image | None":
    import io, time, requests as _req
    api_token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not api_token:
        return None
    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    try:
        resp = _req.post(
            "https://api.replicate.com/v1/models/black-forest-labs/flux-1.1-pro/predictions",
            headers=headers,
            json={"input": {"prompt": prompt, "aspect_ratio": "1:1", "output_format": "jpg", "output_quality": 95, "prompt_upsampling": True, "safety_tolerance": 5}},
            timeout=30,
        )
        resp.raise_for_status()
        prediction_url = resp.json()["urls"]["get"]
        for _ in range(60):
            time.sleep(3)
            r = _req.get(prediction_url, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            if data["status"] == "succeeded":
                img_url = data["output"][0] if isinstance(data["output"], list) else data["output"]
                img_data = _req.get(img_url, timeout=60).content
                return Image.open(io.BytesIO(img_data)).convert("RGB")
            elif data["status"] == "failed":
                logger.warning("Replicate falhou: %s", data.get("error"))
                return None
        logger.warning("Replicate: timeout aguardando geração")
    except Exception as e:
        logger.warning("Falha ao gerar imagem Replicate: %s", e)
    return None


def _fetch_fal_image(prompt: str) -> "Image.Image | None":
    import io, requests as _req
    api_key = os.environ.get("FAL_KEY", "")
    if not api_key:
        return None
    try:
        import fal_client
        os.environ["FAL_KEY"] = api_key
        result = fal_client.subscribe(
            "fal-ai/flux-pro/v1.1",
            arguments={
                "prompt": prompt,
                "image_size": "square_hd",
                "num_images": 1,
                "output_format": "jpeg",
                "guidance_scale": 3.5,
                "num_inference_steps": 28,
                "safety_tolerance": "2",
            },
        )
        url = result["images"][0]["url"]
        img_data = _req.get(url, timeout=30).content
        return Image.open(io.BytesIO(img_data)).convert("RGB")
    except Exception as e:
        logger.warning("Falha ao gerar imagem fal.ai: %s", e)
    return None


def _fetch_gemini_image(prompt: str) -> "Image.Image | None":
    import io
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_images(
            model="imagen-3.0-generate-001",
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="1:1",
                output_mime_type="image/png",
            ),
        )
        img_bytes = response.generated_images[0].image.image_bytes
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        logger.warning("Falha ao gerar imagem Gemini Imagen: %s", e)
    return None


def _fetch_hf_image(prompt: str) -> "Image.Image | None":
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        return None
    try:
        from huggingface_hub import InferenceClient
        client = InferenceClient(token=token)
        img = client.text_to_image(
            prompt,
            model="black-forest-labs/FLUX.1-schnell",
            width=1024,
            height=1024,
        )
        return img.convert("RGB")
    except Exception as e:
        logger.warning("Falha ao buscar imagem HF: %s", e)
    return None


def _fetch_qwen_image(prompt: str) -> "Image.Image | None":
    import io, time, requests as _req
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    try:
        resp = _req.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
            headers=headers,
            json={
                "model": "qwen-image2.0",
                "input": {"prompt": prompt},
                "parameters": {"size": "1024*1024", "n": 1},
            },
            timeout=30,
        )
        resp.raise_for_status()
        task_id = resp.json().get("output", {}).get("task_id")
        if not task_id:
            logger.warning("Qwen image: task_id não retornado")
            return None

        for _ in range(30):
            time.sleep(3)
            r = _req.get(
                f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            r.raise_for_status()
            output = r.json().get("output", {})
            status = output.get("task_status")
            if status == "SUCCEEDED":
                url = output["results"][0]["url"]
                img_data = _req.get(url, timeout=30).content
                return Image.open(io.BytesIO(img_data)).convert("RGB")
            elif status in ("FAILED", "CANCELED"):
                logger.warning("Qwen image task falhou: %s", output.get("message"))
                return None

        logger.warning("Qwen image: timeout aguardando geração")
    except Exception as e:
        logger.warning("Falha ao gerar imagem Qwen: %s", e)
    return None


def _fetch_ai_image(prompt: str) -> "tuple[Image.Image | None, str | None]":
    """Retorna (imagem, fonte) — fonte é 'qwen', 'ideogram', 'replicate', 'fal', 'leonardo', 'gemini', 'hf', ou None."""
    img = _fetch_qwen_image(prompt)
    if img is not None:
        return img, "qwen"
    img = _fetch_ideogram_image(prompt)
    if img is not None:
        return img, "ideogram"
    img = _fetch_replicate_image(prompt)
    if img is not None:
        return img, "replicate"
    img = _fetch_fal_image(prompt)
    if img is not None:
        return img, "fal"
    img = _fetch_leonardo_image(prompt)
    if img is not None:
        return img, "leonardo"
    img = _fetch_gemini_image(prompt)
    if img is not None:
        return img, "gemini"
    img = _fetch_hf_image(prompt)
    if img is not None:
        return img, "hf"
    return None, None


_FONTS_DIR = Path(__file__).parent.parent / "assets" / "fonts"


def _mfont(size: int, style: str = "Bold"):
    """Carrega Montserrat com suporte completo ao português."""
    name = "Montserrat-Italic.ttf" if style == "Italic" else "Montserrat.ttf"
    try:
        return ImageFont.truetype(str(_FONTS_DIR / name), size)
    except (OSError, IOError):
        return _font(size)


def _overlay_branding(img: Image.Image,
                      cor_escura: tuple, cor_acento: tuple,
                      titulo: str, badge_texto: str,
                      linha1: str, linha2: str,
                      variacao: int = 0) -> Image.Image:
    """Design orgânico profissional com Montserrat sobre foto AI."""
    GREEN_DARK = cor_escura
    GOLD       = cor_acento
    WHITE      = (255, 255, 255)

    # subtítulo real do tópico
    subtitulo = _subtitulo(titulo)
    # badge sem emojis especiais
    num = badge_texto.replace("✦", "").strip().split()[0]
    badge = f"{num} EXERCICIOS"

    base = img.resize(SIZE, Image.LANCZOS).convert("RGBA")

    overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    ov = ImageDraw.Draw(overlay)

    # Faixa topo sólida
    ov.polygon([(0,0),(1200,0),(1200,200),(1000,170),(800,210),(600,175),(400,215),(200,175),(0,210)],
               fill=(*GREEN_DARK, 248))

    # Gradiente base
    for i in range(280):
        alpha = int(248 * (i / 280) ** 1.4)
        ov.rectangle([(0, 920 + i),(1200, 921 + i)], fill=(*GREEN_DARK, alpha))
    ov.rectangle([(0, 1060),(1200, 1200)], fill=(*GREEN_DARK, 248))

    base = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(base)

    # --- TOPO ---
    # Ícone
    cx, cy = 600, 62
    draw.ellipse([(cx-28, cy-28),(cx+28, cy+28)], outline=WHITE, width=2)
    draw.ellipse([(cx-11, cy-18),(cx+11, cy+4)], fill=WHITE)
    draw.ellipse([(cx-10, cy-2),(cx+10, cy+16)], fill=(*GREEN_DARK, 200))

    # COGNIVITA
    f_brand = _mfont(50)
    bw, _ = _text_size(draw, "COGNIVITA", f_brand)
    draw.text(((1200 - bw) // 2, 100), "COGNIVITA", font=f_brand, fill=WHITE)

    # Linha dourada fina
    draw.rectangle([(460, 162),(740, 165)], fill=(*GOLD, 220))

    # Tagline
    f_tag = _mfont(26, "Regular")
    tw, _ = _text_size(draw, "Estimulacao Cognitiva Terapeutica", f_tag)
    draw.text(((1200 - tw) // 2, 174), "Estimacao Cognitiva Terapeutica",
              font=f_tag, fill=(*WHITE, 190))

    # --- BASE ---
    # Título
    f_title = _mfont(82)
    lines = _wrap(titulo.upper(), f_title, 1060, draw)
    if len(lines) > 2:
        f_title = _mfont(64)
        lines = _wrap(titulo.upper(), f_title, 1060, draw)

    ty = 940
    for line in lines:
        lw, lh = _text_size(draw, line, f_title)
        draw.text(((1200 - lw) // 2, ty), line, font=f_title, fill=WHITE)
        ty += lh + 10

    # Subtítulo
    f_sub = _mfont(30, "Italic")
    lines_sub = _wrap(subtitulo, f_sub, 1000, draw)
    ty += 8
    for line in lines_sub:
        lw, _ = _text_size(draw, line, f_sub)
        draw.text(((1200 - lw) // 2, ty), line, font=f_sub, fill=(*WHITE, 200))
        ty += 38

    # Badge
    f_badge = _mfont(32)
    bw, bh = _text_size(draw, badge, f_badge)
    bx = (1200 - bw - 60) // 2
    by = ty + 10
    draw.rounded_rectangle([(bx, by),(bx + bw + 60, by + bh + 20)],
                            radius=24, fill=(*GOLD, 220))
    draw.text((bx + 30, by + 10), badge, font=f_badge, fill=(*GREEN_DARK, 255))

    return base.convert("RGB")


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------

def _layout_centrado(img: Image.Image, draw: ImageDraw.ImageDraw,
                     cor_escura, cor_clara, cor_acento,
                     titulo, badge_texto, linha1, linha2, beneficios,
                     variacao):
    """Layout A (v1, v4): livro centralizado, fundo claro."""
    draw.rectangle([(0, 0), (1200, 1200)], fill=cor_clara)
    _draw_header(draw, cor_escura, cor_acento)

    # Elemento decorativo de fundo (grid de pontos)
    dot_col = _blend(cor_escura, cor_clara, 0.93)
    for gx in range(60, 1200, 80):
        for gy in range(100, 940, 80):
            draw.ellipse([(gx - 3, gy - 3), (gx + 3, gy + 3)], fill=dot_col)

    # Mockup do livro
    bk_cx = 600
    bk_w, bk_h = 520, 640
    _draw_book_mockup(
        draw, img,
        bk_cx - bk_w // 2, 108, bk_cx + bk_w // 2, 108 + bk_h,
        cor_escura, cor_clara, titulo, "Apostila Física"
    )

    # Badge abaixo do livro
    _draw_badge(draw, 600, 808, badge_texto, cor_escura, cor_acento)

    # Chips de benefício
    _draw_benefit_chips(draw, beneficios, 878, cor_escura, cor_clara)

    _draw_footer(draw, cor_escura, cor_acento, linha1, linha2, y0=970)


def _layout_split(img: Image.Image, draw: ImageDraw.ImageDraw,
                  cor_escura, cor_clara, cor_acento,
                  titulo, badge_texto, linha1, linha2, beneficios,
                  variacao):
    """Layout B (v2, v5): painel escuro à esquerda com livro, texto à direita."""
    draw.rectangle([(0, 0), (1200, 1200)], fill=cor_clara)

    panel_w = 520
    draw.rectangle([(0, 0), (panel_w, 1200)], fill=cor_escura)

    # Logo no painel escuro
    font_logo = _font(38)
    lw, _ = _text_size(draw, "COGNIVITA", font_logo)
    draw.text(((panel_w - lw) // 2, 36), "COGNIVITA", font=font_logo, fill=(255, 255, 255))
    draw.rectangle([(60, 90), (panel_w - 60, 94)], fill=_blend(cor_escura, (255, 255, 255), 0.45))

    # Mockup no painel esquerdo — cores normais (escuro para lombada, claro para capa)
    bk_w, bk_h = 400, 480
    bk_x0 = (panel_w - bk_w) // 2
    _draw_book_mockup(
        draw, img,
        bk_x0, 108, bk_x0 + bk_w, 108 + bk_h,
        cor_escura, cor_clara, titulo, ""
    )

    # Badge abaixo do mockup
    badge_bg = _blend(cor_escura, (255, 255, 255), 0.15)
    _draw_badge(draw, panel_w // 2, 650, badge_texto, badge_bg, (255, 255, 255))

    # Texto extra no painel esquerdo (exercícios de estimulação cognitiva)
    font_panel_sub = _font_regular(27)
    sub_text = "Estimulação Cognitiva"
    stw, _ = _text_size(draw, sub_text, font_panel_sub)
    draw.text(((panel_w - stw) // 2, 710), sub_text, font=font_panel_sub,
              fill=_blend(cor_escura, (255, 255, 255), 0.55))
    sub_text2 = "para Idosos 60+"
    stw2, _ = _text_size(draw, sub_text2, font_panel_sub)
    draw.text(((panel_w - stw2) // 2, 746), sub_text2, font=font_panel_sub,
              fill=_blend(cor_escura, (255, 255, 255), 0.55))

    # Lado direito: título, benefícios e especificações
    rx0 = panel_w + 44
    rw = 1200 - rx0 - 44

    # Categoria acima do título
    font_cat = _font_regular(28)
    cat_text = "APOSTILA DE ESTIMULAÇÃO COGNITIVA"
    draw.text((rx0, 108), cat_text, font=font_cat, fill=_blend(cor_escura, (255, 255, 255), 0.4))

    font_topic = _font(72)
    lines = _wrap(titulo.upper(), font_topic, rw, draw)
    if len(lines) > 3:
        font_topic = _font(56)
        lines = _wrap(titulo.upper(), font_topic, rw, draw)

    ty = 152
    for line in lines:
        _, lh = _text_size(draw, line, font_topic)
        draw.text((rx0, ty), line, font=font_topic, fill=cor_escura)
        ty += lh + 8

    draw.rectangle([(rx0, ty + 18), (1200 - 44, ty + 22)], fill=_blend(cor_escura, (255, 255, 255), 0.6))
    ty += 52

    font_sub = _font_regular(36)
    draw.text((rx0, ty), "Para Idosos 60+", font=font_sub,
              fill=_blend(cor_escura, (255, 255, 255), 0.28))
    ty += 64

    # Benefícios
    font_b = _font_regular(32)
    for ben in beneficios:
        draw.ellipse([(rx0, ty + 10), (rx0 + 16, ty + 26)], fill=cor_escura)
        draw.text((rx0 + 28, ty), ben, font=font_b, fill=cor_escura)
        ty += 54

    ty += 20
    draw.rectangle([(rx0, ty), (1200 - 44, ty + 2)], fill=_blend(cor_escura, (255, 255, 255), 0.7))
    ty += 22

    # Especificações rápidas
    font_spec = _font_regular(28)
    specs = ["Tamanho A4  ·  Impressão P&B", "Fonte Ampliada para Idosos", "Apostila Física Encadernada"]
    for sp in specs:
        draw.text((rx0, ty), sp, font=font_spec, fill=_blend(cor_escura, (255, 255, 255), 0.3))
        ty += 42

    _draw_footer(draw, cor_escura, cor_acento, linha1, linha2, y0=1040)


def _layout_lateral(img: Image.Image, draw: ImageDraw.ImageDraw,
                    cor_escura, cor_clara, cor_acento,
                    titulo, badge_texto, linha1, linha2, beneficios,
                    variacao):
    """Layout C (v3, v6): livro à direita, texto à esquerda, fundo claro."""
    draw.rectangle([(0, 0), (1200, 1200)], fill=cor_clara)

    # Faixa de acento no topo
    _draw_header(draw, cor_escura, cor_acento)

    # Faixa lateral colorida na direita
    draw.rectangle([(780, 92), (1200, 1200)], fill=_blend(cor_escura, cor_clara, 0.9))

    # Mockup do livro no lado direito
    bk_w, bk_h = 380, 500
    bk_x0 = 800
    _draw_book_mockup(
        draw, img,
        bk_x0, 140, bk_x0 + bk_w, 140 + bk_h,
        cor_escura, cor_clara, titulo, "Apostila Física"
    )

    # Badge abaixo do livro
    _draw_badge(draw, bk_x0 + bk_w // 2, 710, badge_texto, cor_escura, cor_acento)

    # Texto lado esquerdo
    lx0 = 60
    lw_max = 680

    font_topic = _font(62)
    lines = _wrap(titulo.upper(), font_topic, lw_max, draw)
    if len(lines) > 3:
        font_topic = _font(50)
        lines = _wrap(titulo.upper(), font_topic, lw_max, draw)

    ty = 160
    for line in lines:
        _, lh = _text_size(draw, line, font_topic)
        draw.text((lx0, ty), line, font=font_topic, fill=cor_escura)
        ty += lh + 8

    # Linha decorativa
    draw.rectangle([(lx0, ty + 16), (lx0 + 300, ty + 20)], fill=cor_escura)
    ty += 52

    font_sub = _font_regular(34)
    draw.text((lx0, ty), "Estimulação Cognitiva", font=font_sub, fill=_blend(cor_escura, (255, 255, 255), 0.25))
    draw.text((lx0, ty + 44), "para Idosos 60+", font=font_sub, fill=_blend(cor_escura, (255, 255, 255), 0.25))
    ty += 110

    # Benefícios
    font_chip = _font_regular(29)
    for ben in beneficios:
        chip_w, chip_h = _text_size(draw, ben, font_chip)
        chip_w += 32
        chip_bg = _blend(cor_escura, (255, 255, 255), 0.88)
        chip_border = _blend(cor_escura, (255, 255, 255), 0.65)
        draw.rounded_rectangle([(lx0, ty), (lx0 + chip_w, ty + 46)], radius=23, fill=chip_bg, outline=chip_border)
        draw.text((lx0 + 16, ty + (46 - chip_h) // 2), ben, font=font_chip, fill=cor_escura)
        ty += 58

    _draw_footer(draw, cor_escura, cor_acento, linha1, linha2, y0=1040)


# ---------------------------------------------------------------------------
# Geração de uma capa
# ---------------------------------------------------------------------------

_LAYOUT_MAP = {
    1: _layout_centrado,
    2: _layout_split,
    3: _layout_lateral,
    4: _layout_centrado,
    5: _layout_split,
    6: _layout_lateral,
}


def _overlay_typography(
    img: Image.Image,
    cor_escura: tuple, cor_acento: tuple,
    titulo: str, badge_texto: str, linha2: str,
    beneficios: list[str],
    variacao: int,
) -> Image.Image:
    """Overlay cirúrgico de tipografia sobre foto Leonardo. Só adiciona texto, não cobre a foto."""
    base = img.resize(SIZE, Image.LANCZOS).convert("RGBA")
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    verde = cor_escura
    branco = (255, 255, 255)
    sombra = (0, 0, 0, 160)

    if variacao == 1:
        # --- Capa do livro (esquerda, coords estimadas para prompt v1) ---
        cx0, cy0, cx1, cy1 = 60, 160, 440, 960
        cw, ch = cx1 - cx0, cy1 - cy0

        # Fundo branco da capa
        canvas.paste(Image.new("RGBA", (cw, ch), (255, 255, 255, 245)), (cx0, cy0))
        cdraw = ImageDraw.Draw(canvas)

        # Barra verde topo
        bar_h = int(ch * 0.13)
        cdraw.rectangle([(cx0, cy0), (cx1, cy0 + bar_h)], fill=(*verde, 255))
        font_brand = _font(int(bar_h * 0.52))
        bw, _ = _text_size(cdraw, "CogniVita", font_brand)
        cdraw.text((cx0 + (cw - bw) // 2, cy0 + bar_h // 2 - int(bar_h * 0.26)),
                   "CogniVita", font=font_brand, fill=branco)

        # Título centralizado na capa
        font_title = _font(int(cw * 0.13))
        lines = _wrap(titulo.upper(), font_title, cw - 24, cdraw)
        if len(lines) > 3:
            font_title = _font(int(cw * 0.10))
            lines = _wrap(titulo.upper(), font_title, cw - 24, cdraw)
        total_h = sum(_text_size(cdraw, l, font_title)[1] + 8 for l in lines)
        ty = cy0 + bar_h + (ch - bar_h - total_h) // 2 - 20
        for line in lines:
            lw, lh = _text_size(cdraw, line, font_title)
            cdraw.text((cx0 + (cw - lw) // 2, ty), line, font=font_title, fill=verde)
            ty += lh + 8

        # "Para Idosos 60+" abaixo do título
        font_sub = _font_regular(int(cw * 0.09))
        sub = "Para Idosos 60+"
        sw, _ = _text_size(cdraw, sub, font_sub)
        cdraw.text((cx0 + (cw - sw) // 2, ty + 12), sub, font=font_sub,
                   fill=(*verde, 180))

        # --- Headline no topo (com sombra para legibilidade) ---
        font_h = _font(68)
        headline = titulo.upper()
        hlines = _wrap(headline, font_h, 720, draw)
        hy = 28
        for hl in hlines[:2]:
            draw.text((470 + 3, hy + 3), hl, font=font_h, fill=(0, 0, 0, 140))
            draw.text((470, hy), hl, font=font_h, fill=(*verde, 255))
            hy += _text_size(draw, hl, font_h)[1] + 6

        # --- Painel de benefícios (canto inferior direito) ---
        bx0, by0 = 460, 730
        bp_w, bp_h = 720, 440
        panel = Image.new("RGBA", (bp_w, bp_h), (255, 255, 255, 230))
        pr = ImageDraw.Draw(panel)
        font_b = _font_regular(36)
        checkmark = "✓"
        font_ck = _font(38)
        py = 24
        for ben in beneficios[:5]:
            pr.text((16, py), checkmark, font=font_ck, fill=(*verde, 255))
            pr.text((68, py + 2), ben, font=font_b, fill=(*verde, 255))
            py += 72
        canvas.paste(panel, (bx0, by0), panel)

    elif variacao == 2:
        # --- Barra de marca no topo (fina, elegante) ---
        bar_h = 72
        bar = Image.new("RGBA", (1200, bar_h), (*verde, 220))
        bdraw = ImageDraw.Draw(bar)
        font_brand = _font(40)
        bw, bh = _text_size(bdraw, "CogniVita", font_brand)
        bdraw.text(((1200 - bw) // 2, (bar_h - bh) // 2), "CogniVita",
                   font=font_brand, fill=branco)
        canvas.paste(bar, (0, 0), bar)

        # --- Faixa inferior com título ---
        bot_h = 130
        bot = Image.new("RGBA", (1200, bot_h), (*verde, 215))
        bdraw2 = ImageDraw.Draw(bot)
        font_t = _font(48)
        lines = _wrap(titulo.upper(), font_t, 1100, bdraw2)
        ty = (bot_h - len(lines) * 58) // 2
        for line in lines[:2]:
            lw, _ = _text_size(bdraw2, line, font_t)
            bdraw2.text(((1200 - lw) // 2, ty), line, font=font_t, fill=branco)
            ty += 58
        canvas.paste(bot, (0, 1200 - bot_h), bot)

    elif variacao == 3:
        # --- Capa do livro (centro, coords estimadas para prompt v3) ---
        cx0, cy0, cx1, cy1 = 195, 55, 755, 1060
        cw, ch = cx1 - cx0, cy1 - cy0

        canvas.paste(Image.new("RGBA", (cw, ch), (255, 255, 255, 230)), (cx0, cy0))
        cdraw = ImageDraw.Draw(canvas)

        # Barra verde topo
        bar_h = int(ch * 0.12)
        cdraw.rectangle([(cx0, cy0), (cx1, cy0 + bar_h)], fill=(*verde, 255))
        font_brand = _font(int(bar_h * 0.52))
        bw, _ = _text_size(cdraw, "CogniVita", font_brand)
        cdraw.text((cx0 + (cw - bw) // 2, cy0 + bar_h // 2 - int(bar_h * 0.26)),
                   "CogniVita", font=font_brand, fill=branco)

        # Título
        font_title = _font(int(cw * 0.13))
        lines = _wrap(titulo.upper(), font_title, cw - 32, cdraw)
        if len(lines) > 3:
            font_title = _font(int(cw * 0.10))
            lines = _wrap(titulo.upper(), font_title, cw - 32, cdraw)
        total_h = sum(_text_size(cdraw, l, font_title)[1] + 10 for l in lines)
        ty = cy0 + bar_h + (ch - bar_h - total_h) // 2 - 30
        for line in lines:
            lw, lh = _text_size(cdraw, line, font_title)
            cdraw.text((cx0 + (cw - lw) // 2, ty), line, font=font_title, fill=verde)
            ty += lh + 10

        # Subtítulo
        font_sub = _font_regular(int(cw * 0.08))
        sub = "Estimulação Cognitiva"
        sw, _ = _text_size(cdraw, sub, font_sub)
        cdraw.text((cx0 + (cw - sw) // 2, ty + 16), sub, font=font_sub,
                   fill=(*verde, 180))

    result = Image.alpha_composite(base, canvas)
    return result.convert("RGB")


def _gerar_capa(
    path: Path,
    variacao: int,
    titulo: str,
    badge_texto: str,
    rodape_linha1: str,
    rodape_linha2: str,
    beneficios: list[str] = None,
    ai_image: "Image.Image | None" = None,
    ai_source: "str | None" = None,
):
    cor_escura_hex, cor_clara_hex, cor_acento_hex = PALETAS[variacao]
    cor_escura = _hex(cor_escura_hex)
    cor_clara = _hex(cor_clara_hex)
    cor_acento = _hex(cor_acento_hex)

    if beneficios is None:
        beneficios = _BENEFICIOS_PADRAO

    if variacao in (1, 2, 3):
        if ai_image is not None:
            # Salva foto AI diretamente sem overlay
            ai_image.resize(SIZE, Image.LANCZOS).convert("RGB").save(str(path), "PNG")
            return
        else:
            # Leonardo falhou: fundo verde sólido simples, sem overlay pesado com texto
            img = Image.new("RGB", SIZE, color=(20, 70, 45))
            img.save(str(path), "PNG")
            return

    # Fallback: layout Pillow puro (v4-v6)
    img = Image.new("RGB", SIZE, color=cor_clara)
    draw = ImageDraw.Draw(img)
    layout_fn = _LAYOUT_MAP.get(variacao, _layout_centrado)
    layout_fn(img, draw, cor_escura, cor_clara, cor_acento,
              titulo, badge_texto, rodape_linha1, rodape_linha2, beneficios, variacao)
    img.save(str(path), "PNG")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def _fetch_ai_images_for_variacoes(variacoes: list[int], prompts: dict) -> dict:
    """Busca imagens AI para as variações 1-3. Retorna dict v -> (imagem, fonte)."""
    ai_needed = [v for v in variacoes if v in prompts]
    ai_images = {}
    for v in ai_needed:
        img, source = _fetch_ai_image(prompts[v])
        if img is not None:
            ai_images[v] = (img, source)
        else:
            logger.info("AI indisponível para variação %s, usando Pillow puro", v)
    return ai_images


POOL_DIR = OUTPUT_DIR.parent / "images" / "pool"


def _pick_pool(variacao: int) -> "str | None":
    """Retorna caminho aleatório do pool para v2 ou v3, ou None se pool vazio."""
    import random
    pool = POOL_DIR / f"v{variacao}"
    if not pool.exists():
        return None
    imgs = list(pool.glob("*.png"))
    return str(random.choice(imgs)) if imgs else None


def gerar_pool(n: int = 10) -> dict:
    """Gera n imagens para o pool de v2 (lifestyle) e v3 (flat lay).
    Deve ser chamado uma vez antes de começar a publicar produtos.
    Retorna dict com paths gerados por variação.
    """
    POOL_DIR.mkdir(parents=True, exist_ok=True)
    for v in [2, 3]:
        (POOL_DIR / f"v{v}").mkdir(parents=True, exist_ok=True)

    prompts = _build_ai_prompts("Exercicios Cognitivos", 60)
    resultado = {2: [], 3: []}

    for v in [2, 3]:
        for i in range(n):
            img, src = _fetch_ai_image(prompts[v])
            fname = POOL_DIR / f"v{v}" / f"pool_{v}_{i:03d}.png"
            if img is not None:
                img.resize(SIZE, Image.LANCZOS).convert("RGB").save(str(fname), "PNG")
                resultado[v].append(str(fname))
                logger.info("Pool v%s gerado: %s", v, fname.name)
            else:
                logger.warning("Pool v%s item %s: AI indisponível", v, i)

    return resultado


def gerar_capas(
    apostila_id: int,
    topico: dict,
    num_exercicios: int,
    variacao: int = None,
) -> list[str]:
    """Gera capas para uma apostila individual.
    V1 é sempre gerada nova. V2 e V3 vêm do pool (se disponível).
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    titulo = topico.get("nome", "Exercícios")
    badge = f"✦ {num_exercicios} EXERCÍCIOS ✦"
    rodape1 = "APOSTILA FÍSICA"
    rodape2 = "Impressa e Encadernada · Para Idosos 60+"

    paths = []

    if variacao is not None:
        # Modo manual: gera a variação solicitada normalmente
        prompts = _build_ai_prompts(titulo, num_exercicios)
        ai_images = _fetch_ai_images_for_variacoes([variacao], prompts)
        fname = OUTPUT_DIR / f"apostila_{apostila_id}_v{variacao}.png"
        ai_entry = ai_images.get(variacao)
        ai_img, ai_src = ai_entry if ai_entry else (None, None)
        _gerar_capa(fname, variacao, titulo, badge, rodape1, rodape2,
                    ai_image=ai_img, ai_source=ai_src)
        return [str(fname)]

    # V1: sempre gera nova (capa principal do produto)
    prompts = _build_ai_prompts(titulo, num_exercicios)
    ai_images = _fetch_ai_images_for_variacoes([1], prompts)
    fname_v1 = OUTPUT_DIR / f"apostila_{apostila_id}_v1.png"
    ai_entry = ai_images.get(1)
    ai_img, ai_src = ai_entry if ai_entry else (None, None)
    _gerar_capa(fname_v1, 1, titulo, badge, rodape1, rodape2,
                ai_image=ai_img, ai_source=ai_src)
    paths.append(str(fname_v1))

    # V2 e V3: usa pool se disponível, senão gera nova
    for v in [2, 3]:
        fname = OUTPUT_DIR / f"apostila_{apostila_id}_v{v}.png"
        pool_path = _pick_pool(v)
        if pool_path:
            import shutil
            shutil.copy(pool_path, str(fname))
            logger.info("V%s: usando pool %s", v, Path(pool_path).name)
        else:
            ai_images_v = _fetch_ai_images_for_variacoes([v], prompts)
            ai_entry = ai_images_v.get(v)
            ai_img, ai_src = ai_entry if ai_entry else (None, None)
            _gerar_capa(fname, v, titulo, badge, rodape1, rodape2,
                        ai_image=ai_img, ai_source=ai_src)
        paths.append(str(fname))

    return paths


def gerar_capas_kit(
    kit_id: int,
    kit_nome: str,
    apostilas: list[dict],
    variacao: int = None,
) -> list[str]:
    """Gera capas para um kit de apostilas."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total_exercicios = sum(a.get("num_exercicios", 0) for a in apostilas)
    badge = f"✦ {total_exercicios} EXERCÍCIOS ✦"
    rodape1 = f"KIT {len(apostilas)} EM 1"
    rodape2 = "Apostilas Físicas · Para Idosos 60+"

    variacoes = [variacao] if variacao is not None else [1, 2, 3]
    prompts = _build_ai_prompts(kit_nome, total_exercicios)
    ai_images = _fetch_ai_images_for_variacoes(variacoes, prompts)
    paths = []

    for v in variacoes:
        fname = OUTPUT_DIR / f"kit_{kit_id}_v{v}.png"
        ai_entry = ai_images.get(v)
        ai_img, ai_src = ai_entry if ai_entry else (None, None)
        _gerar_capa(fname, v, kit_nome, badge, rodape1, rodape2,
                    ai_image=ai_img, ai_source=ai_src)
        paths.append(str(fname))

    return paths


def gerar_capa_produto(
    apostila_id: int,
    nome_produto: str,
    topico: dict,
    num_exercicios: int,
    posicao: int,
    serie: int = 1,
) -> list[str]:
    """Gera 3 capas para uma apostila de linha de produto.

    Sempre produz v1 (produto AI), v2 e v3 (pool ou AI).
    Retorna [v1_path, v2_path, v3_path] — o primeiro é o imagem_path do anúncio.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    titulo_capa = f"{nome_produto} {_to_roman(serie)}"
    badge   = f"✦ {num_exercicios} EXERCÍCIOS ✦"
    rodape1 = titulo_capa.upper()
    rodape2 = f"{num_exercicios} Exercícios · Apostila Física · Para Idosos 60+"
    prompts = _build_ai_prompts(titulo_capa, num_exercicios)

    paths = []

    # V1: sempre gera nova imagem AI (produto em destaque)
    fname_v1 = OUTPUT_DIR / f"apostila_{apostila_id}_v1.png"
    ai_images_v1 = _fetch_ai_images_for_variacoes([1], prompts)
    ai_entry = ai_images_v1.get(1)
    ai_img, ai_src = ai_entry if ai_entry else (None, None)
    _gerar_capa(fname_v1, 1, titulo_capa, badge, rodape1, rodape2,
                ai_image=ai_img, ai_source=ai_src)
    paths.append(str(fname_v1))

    # V2 e V3: usa pool se disponível, senão gera via AI
    for v in [2, 3]:
        fname = OUTPUT_DIR / f"apostila_{apostila_id}_v{v}.png"
        pool_path = _pick_pool(v)
        if pool_path:
            import shutil
            shutil.copy(pool_path, str(fname))
            logger.info("V%s: usando pool %s para apostila %s", v, Path(pool_path).name, apostila_id)
        else:
            ai_images_v = _fetch_ai_images_for_variacoes([v], prompts)
            ai_entry_v = ai_images_v.get(v)
            ai_img_v, ai_src_v = ai_entry_v if ai_entry_v else (None, None)
            _gerar_capa(fname, v, titulo_capa, badge, rodape1, rodape2,
                        ai_image=ai_img_v, ai_source=ai_src_v)
        paths.append(str(fname))

    return paths
