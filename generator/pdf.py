"""
generator/pdf.py
Cognivita — geração de PDF via Playwright (HTML → PDF A4).

Função principal:
  gerar_pdf(apostila_id, topico, conteudo_json) -> str  (caminho absoluto do PDF)
"""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from generator.html_render import render_apostila_html


def gerar_pdf(apostila_id: int, topico: dict, conteudo_json: str, capa_img: str = None) -> str:
    """
    Gera PDF da apostila e salva em output/pdfs/apostila_{apostila_id}.pdf.

    Args:
        apostila_id: ID único da apostila (usado no nome do arquivo).
        topico: dict com pelo menos {"nome": str}.
        conteudo_json: JSON string produzida por generator.content.gerar_conteudo().
        capa_img: caminho local da foto do anúncio — capa do PDF = arte do ML.

    Returns:
        Caminho absoluto para o arquivo PDF gerado.
    """
    html = render_apostila_html(topico, conteudo_json, capa_img=capa_img)

    base_dir = Path(__file__).parent.parent
    output_dir = base_dir / "output" / "pdfs"
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"apostila_{apostila_id}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={"top": "18mm", "right": "20mm", "bottom": "20mm", "left": "20mm"},
        )
        browser.close()

    return str(pdf_path.resolve())


if __name__ == "__main__":
    _topico = {"id": 1, "nome": "Memória", "slug": "memoria"}
    _exercicios = [
        {
            "numero": 1, "tipo": "texto", "titulo": "Recordar Palavras",
            "descricao": "Leia as palavras abaixo e tente memorizá-las antes de cobrir.",
            "instrucoes": ["Leia com calma cada palavra", "Cubra a lista e escreva abaixo"],
            "espaco_resposta": "linha", "dados_visuais": None,
        },
        {
            "numero": 2, "tipo": "ligar", "titulo": "Ligar Palavras",
            "descricao": "Ligue cada item da coluna esquerda com seu par correto à direita.",
            "instrucoes": ["Escreva o número correspondente ao lado de cada letra."],
            "espaco_resposta": "visual",
            "dados_visuais": {"esquerda": ["Cachorro", "Rosa", "Avião"], "direita": ["Flor", "Animal", "Veículo"]},
        },
        {
            "numero": 3, "tipo": "completar", "titulo": "Complete a Frase",
            "descricao": "Escolha a palavra correta da lista para completar as frases.",
            "instrucoes": ["Escreva a palavra no espaço indicado por ___."],
            "espaco_resposta": "visual",
            "dados_visuais": {
                "frases": ["O ___ nasce de manhã e se põe à tarde.", "À noite brilham as ___."],
                "opcoes": ["sol", "estrelas", "lua", "nuvens"],
            },
        },
        {
            "numero": 4, "tipo": "sequencia", "titulo": "Complete a Sequência",
            "descricao": "Qual elemento completa esta sequência lógica?",
            "instrucoes": ["Escreva sua resposta no espaço com ???."],
            "espaco_resposta": "visual",
            "dados_visuais": {"items": ["Primavera", "Verão", "???", "Inverno"]},
        },
        {
            "numero": 5, "tipo": "tabela", "titulo": "Preencha a Tabela",
            "descricao": "Complete a tabela abaixo com suas respostas.",
            "instrucoes": ["Preencha cada célula com a informação solicitada."],
            "espaco_resposta": "visual",
            "dados_visuais": {"colunas": ["Dia da Semana", "Atividade Favorita", "Como me Senti"], "linhas": 5},
        },
        {
            "numero": 6, "tipo": "texto", "titulo": "Minha Semana",
            "descricao": "Descreva em poucas palavras o que de mais marcante aconteceu esta semana.",
            "instrucoes": ["Escreva livremente, sem pressa."],
            "espaco_resposta": "quadrado", "dados_visuais": None,
        },
    ]
    _conteudo = json.dumps(
        {"topico": "Memória", "num_exercicios": 6, "exercicios": _exercicios},
        ensure_ascii=False,
    )
    _path = gerar_pdf(apostila_id=0, topico=_topico, conteudo_json=_conteudo)
    print("PDF gerado em:", _path)
    print("Existe:", os.path.exists(_path), "| Tamanho:", os.path.getsize(_path), "bytes")
