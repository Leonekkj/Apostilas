"""
Gera XLSX de upload em massa da Shopee a partir dos anúncios publicados no ML.
Usa patch direto no XML do template (sem openpyxl) para preservar metadata.

Uso:
    python gerar_shopee_xlsx.py --limite 10
    python gerar_shopee_xlsx.py --limite 125
    python gerar_shopee_xlsx.py --limite 10 --preco 59.99 --categoria 101566
"""
import sys, os, argparse, zipfile, shutil, re, html
from datetime import datetime

PRECO_PADRAO = 59.99

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass

import database

TEMPLATE = r"C:\Users\ideia\Downloads\Shopee_mass_upload_2026-06-09_basic_template.xlsx"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

# Atributos da categoria 101566 (Livros e Revistas > Livros > Carreiras...)
# (attribute_id, value_type, display_name, valor_nos_dados)
ATTRS = [
    (100413, 2, "Condição",        "Novo"),
    (100673, 2, "Idioma",          "Português"),
    (100676, 1, "Importado/Local", "Local"),
    (100707, 2, "Tipo de Edição",  "Edição Regular"),
    (100710, 2, "Tipo de Capa",    "Capa Flexível"),
]
BRAND_COL = 52       # coluna AZ → ps_brand (após AY = última coluna do template)
BASE_ATTR_COL = 53   # começa em BA (atributos de categoria)

# ── helpers ──────────────────────────────────────────────────────────────────

def col_letter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def xml_escape(s):
    return html.escape(str(s or ""), quote=True)

def to_dict(row):
    return dict(row) if hasattr(row, "keys") else row


# ── shared-strings manager ───────────────────────────────────────────────────

class SharedStrings:
    def __init__(self, xml_bytes):
        self.strings = []
        self._parse(xml_bytes)
        self._index = {s: i for i, s in enumerate(self.strings)}

    def _parse(self, xml_bytes):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
        for si in root:
            parts = [t.text or "" for t in si.iter(f"{{{NS}}}t")]
            self.strings.append("".join(parts))

    def get_or_add(self, value: str) -> int:
        s = str(value or "")
        if s in self._index:
            return self._index[s]
        idx = len(self.strings)
        self.strings.append(s)
        self._index[s] = idx
        return idx

    def to_xml(self) -> bytes:
        count = len(self.strings)
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n',
            f'<sst xmlns="{NS}" count="{count}" uniqueCount="{count}">',
        ]
        for s in self.strings:
            parts.append(f'<si><t xml:space="preserve">{xml_escape(s)}</t></si>')
        parts.append("</sst>")
        return "".join(parts).encode("utf-8")


# ── XML row helpers ───────────────────────────────────────────────────────────

def make_cells_xml(row_num: int, cells: dict) -> str:
    parts = []
    for col in sorted(cells.keys()):
        cell_ref = f"{col_letter(col)}{row_num}"
        kind, val = cells[col]
        if kind == "s":
            parts.append(f'<c r="{cell_ref}" t="s"><v>{val}</v></c>')
        else:
            parts.append(f'<c r="{cell_ref}"><v>{val}</v></c>')
    return "".join(parts)

def build_row_xml(row_num: int, cells: dict) -> str:
    return f'<row r="{row_num}">{make_cells_xml(row_num, cells)}</row>'

def inject_cells_into_existing_row(sheet_xml: str, row_num: int, extra_cells_xml: str) -> str:
    """Adiciona células extras antes de </row> na linha row_num."""
    pattern = rf'(<row r="{row_num}"(?:[^>]*)>)(.*?)(</row>)'
    def replacer(m):
        return m.group(1) + m.group(2) + extra_cells_xml + m.group(3)
    result = re.sub(pattern, replacer, sheet_xml, count=1, flags=re.DOTALL)
    return result


# ── database ─────────────────────────────────────────────────────────────────

def fetch_products(limite: int) -> list:
    with database._get_conn() as conn:
        cur = database._cursor(conn)
        cur.execute("""
            SELECT a.id, a.titulo, a.descricao, a.preco, a.ml_id, a.imagem_path
            FROM anuncios a
            WHERE a.status = 'publicado'
              AND a.ml_id IS NOT NULL
              AND a.imagem_path LIKE 'http%%'
            ORDER BY a.id
            LIMIT %s
        """, [limite])
        return [to_dict(r) for r in cur.fetchall()]


def gerar_descricao(titulo: str, descricao: str) -> str:
    if descricao and len(descricao.strip()) > 30:
        return descricao.strip()[:4999]
    nome = titulo or "Apostila Cognitiva"
    return (
        f"{nome}\n\n"
        "Apostila física impressa em papel A4 de alta qualidade.\n\n"
        "✅ Exercícios para estimulação cognitiva\n"
        "✅ Fonte grande e de fácil leitura\n"
        "✅ Ideal para idosos e terceira idade\n"
        "✅ Atividades de memória, atenção e raciocínio\n\n"
        "Enviada pelos Correios com embalagem protetora."
    )


# ── main ──────────────────────────────────────────────────────────────────────

def gerar(limite: int, output_path: str, preco: float = PRECO_PADRAO, categoria_id: str = ""):
    """Modo legado: busca do banco e usa preço fixo (compatibilidade)."""
    print(f"[shopee] Buscando {limite} produtos...")
    produtos = fetch_products(limite)
    for p in produtos:
        p.setdefault("preco", preco)
    print(f"[shopee] {len(produtos)} produtos encontrados")
    gerar_de_produtos(produtos, output_path, categoria_id=categoria_id)


def gerar_de_produtos(produtos: list, output_path: str, categoria_id: str = ""):
    """Gera o XLSX a partir de uma lista de produtos já pronta.

    Cada produto: {titulo, descricao, preco, ml_id, imagem_path}.
    O PREÇO usado é o de cada item (p['preco']) — não mais um valor fixo.
    """
    print(f"[shopee] gerando XLSX com {len(produtos)} produtos")
    shutil.copy2(TEMPLATE, output_path)

    with zipfile.ZipFile(output_path, "r") as zin:
        ss = SharedStrings(zin.read("xl/sharedStrings.xml"))
        sheet2_xml = zin.read("xl/worksheets/sheet2.xml").decode("utf-8")
        other_files = {
            name: zin.read(name)
            for name in zin.namelist()
            if name not in ("xl/sharedStrings.xml", "xl/worksheets/sheet2.xml")
        }

    # ── Injetar colunas de marca + atributos nos headers (linhas 1-4) ──────────
    # Linha 1: chaves técnicas
    row1_cells = {BRAND_COL: ("s", ss.get_or_add("ps_brand|0|0"))}
    row1_cells.update({
        BASE_ATTR_COL + i: ("s", ss.get_or_add(f"attribute.{attr_id}|0|{vtype}"))
        for i, (attr_id, vtype, _, _val) in enumerate(ATTRS)
    })
    sheet2_xml = inject_cells_into_existing_row(sheet2_xml, 1, make_cells_xml(1, row1_cells))

    # Linha 3: nomes legíveis
    row3_cells = {BRAND_COL: ("s", ss.get_or_add("Marca"))}
    row3_cells.update({
        BASE_ATTR_COL + i: ("s", ss.get_or_add(dname))
        for i, (_id, _vt, dname, _val) in enumerate(ATTRS)
    })
    sheet2_xml = inject_cells_into_existing_row(sheet2_xml, 3, make_cells_xml(3, row3_cells))

    # Linha 4: obrigatoriedade
    row4_cells = {BRAND_COL: ("s", ss.get_or_add("Opcional"))}
    row4_cells.update({
        BASE_ATTR_COL + i: ("s", ss.get_or_add("Opcional"))
        for i in range(len(ATTRS))
    })
    sheet2_xml = inject_cells_into_existing_row(sheet2_xml, 4, make_cells_xml(4, row4_cells))

    # ── Construir linhas de dados (7+) ────────────────────────────────────────
    new_rows = []
    for i, p in enumerate(produtos):
        row_num = 7 + i

        titulo = (p["titulo"] or "").strip()
        descricao = gerar_descricao(titulo, p.get("descricao") or "")
        ml_id = p["ml_id"] or ""
        imagem = p["imagem_path"] or ""

        preco_item = float(p.get("preco") or PRECO_PADRAO)
        cells = {
            2:  ("s", ss.get_or_add(titulo)),
            3:  ("s", ss.get_or_add(descricao)),
            4:  ("s", ss.get_or_add(ml_id)),
            11: ("n", f"{preco_item:.2f}"),
            12: ("n", "100"),
            13: ("s", ss.get_or_add(ml_id)),
            16: ("s", ss.get_or_add("0000000000000")),
            18: ("s", ss.get_or_add(imagem)),
            19: ("s", ss.get_or_add(imagem)),
            20: ("s", ss.get_or_add(imagem)),
            27: ("n", "0.30"),
            28: ("n", "29"),
            29: ("n", "21"),
            30: ("n", "1"),
        }
        if categoria_id:
            cells[1] = ("n", categoria_id)

        # Marca e atributos
        cells[BRAND_COL] = ("s", ss.get_or_add("Sem marca"))
        for j, (_attr_id, _vt, _dname, valor) in enumerate(ATTRS):
            cells[BASE_ATTR_COL + j] = ("s", ss.get_or_add(valor))

        new_rows.append(build_row_xml(row_num, cells))
        print(f"  [{i+1}] {titulo[:60]}")

    # ── Injetar dados no XML ──────────────────────────────────────────────────
    if "</sheetData>" in sheet2_xml:
        sheet2_xml = sheet2_xml.replace(
            "</sheetData>",
            "\n".join(new_rows) + "</sheetData>"
        )
    else:
        sheet2_xml = sheet2_xml.replace(
            "</worksheet>",
            f"<sheetData>{''.join(new_rows)}</sheetData></worksheet>"
        )

    tmp = output_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in other_files.items():
            zout.writestr(name, data)
        zout.writestr("xl/sharedStrings.xml", ss.to_xml())
        zout.writestr("xl/worksheets/sheet2.xml", sheet2_xml.encode("utf-8"))

    os.replace(tmp, output_path)
    print(f"\n[shopee] Arquivo gerado: {output_path}")
    print(f"[shopee] {len(produtos)} produtos | {len(ATTRS)} atributos por produto")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limite", type=int, default=10)
    parser.add_argument("--output", default="")
    parser.add_argument("--preco", type=float, default=PRECO_PADRAO)
    parser.add_argument("--categoria", default="")
    args = parser.parse_args()

    if not args.output:
        ts = datetime.now().strftime("%Y-%m-%d")
        args.output = os.path.join(
            os.path.expanduser("~/Downloads"),
            f"shopee_upload_{ts}_{args.limite}produtos.xlsx"
        )

    gerar(args.limite, args.output, preco=args.preco, categoria_id=args.categoria)
