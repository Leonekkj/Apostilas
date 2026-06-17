"""
generator/_pdf_assets.py
Assets de geração do PDF premium: CSS (full-bleed + moldura editorial),
ícones SVG por categoria cognitiva e divisores geométricos.
Sem dependências do projeto — apenas strings.
"""

# Paleta de marca Cognivita
C_DARK = "#0C3322"
C_GREEN = "#1B6B4A"
C_CREAM = "#F7F3EC"
C_TEXT = "#1A2820"
C_MUTED = "#6B7E76"
C_GOLD = "#C49A4A"
C_LIGHT_GREEN = "#C8DDD0"
C_BORDER = "#CFD9D3"

# --- Ícones SVG por categoria (stroke currentColor, herda a cor do contexto) ---
def _svg(body: str) -> str:
    return (
        '<svg class="ex-ic" width="18" height="18" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )

CATEGORY_ICONS = {
    # cérebro — memória
    "memoria": _svg('<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 5 1V5a3 3 0 0 0-2-1z"/>'
                    '<path d="M15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-5 1"/>'),
    # olho — atenção
    "atencao": _svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>'),
    # blocos/encaixe — raciocínio/lógica
    "raciocinio": _svg('<path d="M3 7h7v4H6v6h4M14 7h7v10h-7zM14 11h7"/>'),
    # balão — linguagem
    "linguagem": _svg('<path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-4-1L3 21l2-5.5a8.38 8.38 0 0 1-1-4A8.5 8.5 0 0 1 12.5 3 8.38 8.38 0 0 1 21 11.5z"/>'),
    # estrela/lupa — percepção visual
    "percepcao": _svg('<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>'),
    # folha — geral
    "geral": _svg('<path d="M11 20A7 7 0 0 1 4 13c0-5 6-9 11-9 0 5-1 11-7 11z"/><path d="M11 20c0-4 2-7 6-9"/>'),
}

# tipos de exercício → categoria de ícone (fallback quando não há categoria explícita)
_TIPO_TO_CAT = {
    "ligar": "raciocinio",
    "completar": "linguagem",
    "sequencia": "raciocinio",
    "tabela": "percepcao",
    "texto": "memoria",
}

def icon_for(categoria=None, tipo=None) -> str:
    if categoria:
        chave = str(categoria).strip().lower()
        for cat in CATEGORY_ICONS:
            if cat in chave:
                return CATEGORY_ICONS[cat]
    if tipo:
        cat = _TIPO_TO_CAT.get(str(tipo).strip().lower())
        if cat:
            return CATEGORY_ICONS[cat]
    return CATEGORY_ICONS["geral"]

def divider_svg() -> str:
    return (
        '<svg class="ex-divider" width="120" height="10" viewBox="0 0 120 10" '
        f'stroke="{C_GOLD}" fill="{C_GOLD}" stroke-width="1">'
        '<line x1="0" y1="5" x2="52" y2="5"/>'
        '<rect x="58" y="2" width="4" height="4" transform="rotate(45 60 4)"/>'
        '<line x1="68" y1="5" x2="120" y2="5"/></svg>'
    )

# --- CSS premium (full-bleed + moldura editorial) ---
PREMIUM_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400;1,600&family=DM+Sans:wght@300;400;500&display=swap');

@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: 'DM Sans', Arial, sans-serif;
  color: {C_TEXT};
  font-size: 12.5pt;
  line-height: 1.65;
  background: {C_CREAM};
}}

/* cada .page é uma folha; o fundo creme vai até a borda física */
.page {{
  position: relative;
  background: {C_CREAM};
  padding: 16mm 18mm 18mm 18mm;
  page-break-after: always;
  min-height: 297mm;
}}

/* moldura editorial repetida em cada página (recuada 10mm da borda) + filete dourado no topo */
.page::before {{
  content: "";
  position: absolute;
  top: 10mm; left: 10mm; right: 10mm; bottom: 10mm;
  border: 0.75pt solid {C_GREEN};
  pointer-events: none;
}}
.page::after {{
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2mm;
  background: {C_GOLD};
}}

/* páginas que sangram fundo até a borda (capa/contracapa): sem moldura/filete */
.page.bleed {{ padding: 0; }}
.page.bleed::before, .page.bleed::after {{ display: none; }}

/* === EXERCÍCIO (editorial geométrico) === */
.ex-cat {{
  font-size: 8.5pt; letter-spacing: 0.22em; text-transform: uppercase;
  color: {C_GOLD}; font-weight: 600; margin-bottom: 1mm;
}}
.ex-header {{
  display: flex; align-items: center; gap: 2.5mm;
  color: {C_DARK}; padding-bottom: 1.5mm;
  border-bottom: 1.2pt solid {C_DARK}; margin-bottom: 3mm;
}}
.ex-header .ex-title {{ font-family: 'Cormorant Garamond', serif; font-size: 14pt; font-weight: 600; }}
.ex-ic {{ flex: 0 0 auto; color: {C_GREEN}; }}
.ex-divider {{ display: block; margin: 6mm auto; }}
.answer-label {{
  font-family: 'Cormorant Garamond', serif; font-style: italic;
  font-size: 12pt; color: {C_GREEN}; margin: 3mm 0 2mm 0;
}}
.answer-line {{ border-top: 1px solid {C_BORDER}; margin-bottom: 5mm; }}
.answer-box {{ border: 1px solid {C_BORDER}; background: #fff; border-radius: 4px; height: 50mm; margin: 2mm 0 4mm 0; }}

/* === CAPA com arte IA + overlay de marca === */
.cover-art {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
.cover-grad {{ position: absolute; left: 0; right: 0; bottom: 0; height: 55%;
  background: linear-gradient(180deg, rgba(12,51,34,0) 0%, rgba(12,51,34,0.85) 78%, rgba(12,51,34,0.95) 100%); }}
.cover-top {{ position: absolute; top: 0; left: 0; right: 0; text-align: center; color: {C_CREAM};
  font-size: 10pt; letter-spacing: 0.28em; text-transform: uppercase; padding: 10mm 8mm 0; }}
.cover-bottom {{ position: absolute; left: 0; right: 0; bottom: 0; text-align: center; color: {C_CREAM}; padding: 0 14mm 16mm; }}
.cover-brand {{ font-family: 'Cormorant Garamond', serif; font-size: 16pt; letter-spacing: 0.12em; }}
.cover-rule {{ width: 18mm; height: 1px; background: {C_GOLD}; margin: 3mm auto; border: none; }}
.cover-title {{ font-family: 'Cormorant Garamond', serif; font-size: 30pt; line-height: 1.1; }}
.cover-seal {{ font-size: 10pt; opacity: 0.9; margin-top: 4mm; }}
"""
