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


def _hex_to_rgb(h: str) -> str:
    """'#0C3322' -> '12,51,34' (para uso em rgba())."""
    h = h.lstrip("#")
    return ",".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


C_DARK_RGB = _hex_to_rgb(C_DARK)

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

def icon_for(categoria: str | None = None, tipo: str | None = None) -> str:
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
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,400;1,600&family=DM+Sans:wght@300;400;500&display=swap');

@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}

body {{
  font-family: 'DM Sans', Arial, sans-serif;
  color: {C_TEXT};
  font-size: 12.5pt;
  line-height: 1.65;
  background: {C_CREAM};
}}

/* === MOLDURA EDITORIAL (repetida em TODA folha impressa) ===
   Um único elemento fixed em <body>. Com @page margin:0, o Chromium
   repete elementos fixed em cada página impressa, posicionando-os
   relativos à folha. z-index baixo: capa/contracapa cobrem por cima. */
.sheet-frame {{
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}}
/* keyline verde recuada 10mm da borda física */
.sheet-frame::before {{
  content: "";
  position: absolute;
  top: 10mm; left: 10mm; right: 10mm; bottom: 10mm;
  border: 0.75pt solid {C_GREEN};
}}
/* filete dourado de 2mm no topo */
.sheet-frame::after {{
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2mm;
  background: {C_GOLD};
}}

/* cada .page é uma folha; o fundo creme vai até a borda física.
   z-index acima da moldura fixa, mas o fundo creme é translúcido só
   onde precisa — aqui é sólido, então deixamos padding suficiente para
   que a keyline (desenhada pela moldura fixa atrás) apareça nas bordas. */
.page {{
  position: relative;
  z-index: 1;
  background: transparent;
  padding: 16mm 18mm 18mm 18mm;
  page-break-after: always;
  min-height: 297mm;
}}

/* páginas que sangram fundo até a borda (capa/contracapa): sem moldura.
   z-index alto + fundo sólido full-bleed cobrem a moldura fixa. */
.page.bleed {{
  padding: 0;
  background: {C_CREAM};
  z-index: 2;
  overflow: hidden;
}}
.page.bleed.contracapa {{ background: {C_DARK}; }}

/* === EXERCÍCIO (editorial geométrico) === */
.exercise {{
  margin-bottom: 8mm;
  page-break-inside: avoid;
  break-inside: avoid;
}}
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

.exercise-desc {{
  font-size: 12.5pt;
  text-align: justify;
  margin-bottom: 3mm;
  color: {C_TEXT};
}}
.exercise-steps-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 13pt;
  font-weight: 600;
  color: {C_GREEN};
  margin-bottom: 1mm;
}}
.exercise-step {{
  font-size: 12.5pt;
  padding-left: 6mm;
  margin-bottom: 2mm;
  color: {C_TEXT};
}}

/* === ESPAÇO DE RESPOSTA === */
.answer-label {{
  font-family: 'Cormorant Garamond', serif; font-style: italic;
  font-size: 12pt; color: {C_GREEN}; margin: 3mm 0 2mm 0;
}}
.answer-line {{ border-top: 1px solid {C_BORDER}; margin-bottom: 5mm; }}
.answer-box {{ border: 1px solid {C_BORDER}; background: #fff; border-radius: 4px; height: 50mm; margin: 2mm 0 4mm 0; }}
.answer-bullets {{
  list-style: none;
  margin: 2mm 0;
}}
.answer-bullets li {{
  border-bottom: 1px solid {C_BORDER};
  padding: 5mm 0 1mm 0;
  margin-bottom: 2mm;
  font-size: 12.5pt;
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
  border-left: 1px dashed {C_BORDER};
  border-right: 1px dashed {C_BORDER};
  margin: 0 4mm;
}}
.match-item {{
  border-bottom: 1px solid {C_BORDER};
  padding: 7px 4px;
  font-size: 12.5pt;
}}
.match-item-num, .match-item-letter {{
  font-weight: 500;
  color: {C_GREEN};
  margin-right: 4px;
}}
.match-answer-blank {{
  display: inline-block;
  width: 28px;
  border-bottom: 1px solid {C_TEXT};
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
  border-bottom: 1px solid {C_BORDER};
}}
.completar-blank {{
  display: inline-block;
  min-width: 80px;
  border-bottom: 1.5px solid {C_TEXT};
  margin: 0 4px;
}}
.completar-opcoes {{
  font-size: 12.5pt;
  color: {C_MUTED};
  margin-top: 3mm;
  padding: 7px 12px;
  border: 1px solid {C_BORDER};
  background: #fff;
}}
.completar-opcoes-label {{
  font-weight: 500;
  color: {C_GREEN};
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
  border: 1.5px solid {C_GREEN};
  padding: 8px 18px;
  font-size: 13pt;
  font-weight: 500;
  color: {C_TEXT};
  background: #fff;
}}
.seq-item.blank {{
  border: 1.5px dashed {C_BORDER};
  min-width: 80px;
  color: {C_BORDER};
  text-align: center;
}}
.seq-arrow {{
  font-size: 14pt;
  color: {C_MUTED};
}}

/* === TABELA DE RESPOSTA === */
.response-table {{
  width: 100%;
  border-collapse: collapse;
  margin: 4mm 0;
  font-size: 12.5pt;
}}
.response-table th {{
  background: {C_DARK};
  color: {C_LIGHT_GREEN};
  padding: 8px 12px;
  text-align: left;
  font-weight: 500;
  font-size: 10pt;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.response-table td {{
  border: 1px solid {C_BORDER};
  height: 36px;
  padding: 4px 10px;
  background: #fff;
}}
.response-table tr:nth-child(even) td {{
  background: {C_CREAM};
}}

/* === INSTRUÇÕES / SEÇÕES (cabeçalho de seção) === */
.instructions-header {{
  background: {C_DARK};
  color: {C_LIGHT_GREEN};
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
  color: {C_TEXT};
}}
.instructions-tips-title {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 14pt;
  font-weight: 600;
  color: {C_GREEN};
  margin: 5mm 0 3mm 0;
}}
.instructions-tip {{
  margin-bottom: 3mm;
  padding-left: 4mm;
  color: {C_TEXT};
}}
.instructions-rule {{
  border: none;
  border-top: 1px solid {C_BORDER};
  margin: 6mm 0;
}}
.instructions-footer {{
  font-size: 12.5pt;
  text-align: justify;
  color: {C_MUTED};
}}

/* === APRESENTAÇÃO === */
.apresentacao-body {{
  font-size: 13pt;
  line-height: 1.8;
  text-align: justify;
  color: {C_TEXT};
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
  border-bottom: 1px dotted {C_BORDER};
  padding: 5px 0;
  font-size: 13pt;
}}
.indice-fase-nome {{
  font-family: 'Cormorant Garamond', serif;
  font-size: 14pt;
  color: {C_TEXT};
}}
.indice-secao {{
  font-size: 10pt;
  font-weight: 500;
  color: {C_GREEN};
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}

/* === ABERTURA DE FASE === */
.fase-abertura {{
  min-height: 200mm;
}}
.fase-bar {{
  background: {C_DARK};
  padding: 14px 16px;
  margin-bottom: 8mm;
}}
.fase-num {{
  display: block;
  font-family: 'DM Sans', sans-serif;
  font-size: 9pt;
  font-weight: 500;
  color: {C_LIGHT_GREEN};
  letter-spacing: 0.22em;
  text-transform: uppercase;
  margin-bottom: 2px;
}}
.fase-nome {{
  display: block;
  font-family: 'Cormorant Garamond', serif;
  font-size: 26pt;
  font-weight: 600;
  color: #fff;
  line-height: 1.1;
}}
.fase-secao-tag {{
  display: inline-block;
  border: 1px solid {C_GREEN};
  color: {C_GREEN};
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
  color: {C_MUTED};
  margin-bottom: 6mm;
  padding-bottom: 4mm;
  border-bottom: 1px solid {C_BORDER};
}}
.fase-abertura-text {{
  font-size: 13pt;
  line-height: 1.8;
  text-align: justify;
  color: {C_TEXT};
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
  color: {C_TEXT};
}}
.rotina-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12pt;
}}
.rotina-table th {{
  background: {C_DARK};
  color: {C_LIGHT_GREEN};
  padding: 8px 12px;
  text-align: left;
  font-weight: 500;
  font-size: 9.5pt;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}}
.rotina-table td {{
  border: 1px solid {C_BORDER};
  padding: 8px 12px;
  vertical-align: middle;
}}
.rotina-table tr:nth-child(even) td {{
  background: {C_CREAM};
}}
.rotina-dia {{
  font-weight: 500;
  color: {C_TEXT};
  min-width: 40mm;
}}
.rotina-sugestao {{
  color: {C_MUTED};
}}
.rotina-check {{
  width: 16mm;
  text-align: center;
}}
.rotina-checkbox {{
  width: 14px;
  height: 14px;
  border: 1.5px solid {C_BORDER};
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
  border-bottom: 1px solid {C_BORDER};
  font-size: 12.5pt;
}}
.gabarito-num {{
  font-weight: 700;
  color: {C_GREEN};
  min-width: 20mm;
  font-size: 11pt;
}}
.gabarito-titulo {{
  color: {C_MUTED};
  font-size: 10pt;
  min-width: 50mm;
}}
.gabarito-resposta {{
  color: {C_TEXT};
  flex: 1;
}}

/* === CONTRACAPA (full-bleed escuro) === */
.contracapa {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 297mm;
  text-align: center;
}}
.contracapa-logo {{
  font-family: 'Cormorant Garamond', serif;
  font-weight: 600;
  font-size: 36pt;
  color: #fff;
  letter-spacing: 0.08em;
  margin-bottom: 4mm;
}}
.contracapa-rule {{
  width: 40%;
  border: none;
  border-top: 1px solid {C_GREEN};
  margin: 0 auto 6mm auto;
}}
.contracapa-tagline {{
  font-family: 'DM Sans', sans-serif;
  font-size: 10pt;
  font-weight: 300;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: {C_LIGHT_GREEN};
  margin-bottom: 3mm;
  opacity: 0.8;
}}
.contracapa-domain {{
  font-family: 'Cormorant Garamond', serif;
  font-style: italic;
  font-size: 13pt;
  color: {C_LIGHT_GREEN};
  opacity: 0.7;
}}

/* === CAPA SIMPLES (fallback sem arte IA, full-bleed creme) === */
.cover {{
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  min-height: 297mm;
}}
.cover-brand-bar {{
  width: 100%;
  background: {C_DARK};
  color: {C_LIGHT_GREEN};
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
  color: {C_DARK};
  letter-spacing: 0.08em;
  line-height: 1.1;
  margin-bottom: 5mm;
}}
.cover-tagline {{
  font-family: 'DM Sans', sans-serif;
  font-weight: 300;
  font-size: 10pt;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: {C_MUTED};
  margin-bottom: 10mm;
}}
.cover-subtitle {{
  font-family: 'DM Sans', sans-serif;
  font-weight: 300;
  font-size: 13pt;
  color: {C_MUTED};
  margin-bottom: 32mm;
}}
.cover-footer-bar {{
  width: 100%;
  border-top: 1px solid {C_BORDER};
  background: #fff;
  color: {C_GREEN};
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
  color: {C_MUTED};
}}

/* === CAPA com arte IA + overlay de marca === */
.cover-art {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
.cover-grad {{ position: absolute; left: 0; right: 0; bottom: 0; height: 55%;
  background: linear-gradient(180deg, rgba({C_DARK_RGB},0) 0%, rgba({C_DARK_RGB},0.85) 78%, rgba({C_DARK_RGB},0.95) 100%); }}
.cover-top {{ position: absolute; top: 0; left: 0; right: 0; text-align: center; color: {C_CREAM};
  font-size: 10pt; letter-spacing: 0.28em; text-transform: uppercase; padding: 10mm 8mm 0; }}
.cover-bottom {{ position: absolute; left: 0; right: 0; bottom: 0; text-align: center; color: {C_CREAM}; padding: 0 14mm 16mm; }}
.cover-brand {{ font-family: 'Cormorant Garamond', serif; font-size: 16pt; letter-spacing: 0.12em; }}
.cover-rule {{ width: 18mm; height: 1px; background: {C_GOLD}; margin: 3mm auto; border: none; }}
.cover-title {{ font-family: 'Cormorant Garamond', serif; font-size: 30pt; line-height: 1.1; }}
.cover-seal {{ font-size: 10pt; opacity: 0.9; margin-top: 4mm; }}
"""
