"""validacao.py — regras centrais de validação de anúncios.

Usado em DOIS pontos do pipeline:
  1. Criação  (database.criar_anuncio)  — contexto="criacao"
  2. Publicação (ml.client.publicar_anuncio) — contexto="publicacao"

Política: auto-corrigir quando seguro (truncar título, Vol. N, preço canônico);
bloquear apenas o incorrigível (preço <= 0, título vazio).

Import: só `pricing` no topo; `database` é importado lazy dentro das funções
para evitar ciclo (database.criar_anuncio importa este módulo).
"""

import pricing

TITULO_MAX = 60


def fit_titulo(titulo: str, limit: int = TITULO_MAX) -> str:
    """Trunca no limite de palavras completas, garantindo que 'PDF' apareça quando cabe."""
    if len(titulo) <= limit:
        return titulo
    truncado = titulo[:limit].rsplit(" ", 1)[0].rstrip(" —|·")
    # Se PDF estava no original mas caiu fora, adiciona compacto
    if "PDF" in titulo and "PDF" not in truncado:
        candidato = truncado[:limit - 4].rsplit(" ", 1)[0] + " PDF"
        if len(candidato) <= limit:
            return candidato
    return truncado


def _com_sufixo(titulo: str, sufixo: str, limit: int = TITULO_MAX) -> str:
    """Anexa sufixo recortando o título na palavra para caber no limite."""
    base = titulo[:limit - len(sufixo)].rsplit(" ", 1)[0].rstrip(" —|·,")
    return (base + sufixo)[:limit]


def dedupe_titulos(titulos: list) -> list:
    """Pós-processamento dos títulos vindos do LLM (lista de dicts com chave 'titulo').

    Garante: todos <= 60 chars (corte em palavra) e únicos entre si
    (case-insensitive). Duplicata recebe sufixo ' Vol. N'.
    Modifica os dicts in-place e retorna a lista.
    """
    vistos = set()
    for item in titulos:
        titulo = fit_titulo((item.get("titulo") or "").strip())
        chave = titulo.lower()
        if chave and chave in vistos:
            for n in range(2, 30):
                candidato = _com_sufixo(titulo, f" Vol. {n}")
                if candidato.lower() not in vistos:
                    titulo = candidato
                    break
        item["titulo"] = titulo
        vistos.add(titulo.lower())
    return titulos


def titulo_unico_no_banco(titulo: str, excluir_id=None, incluir_rascunhos: bool = True) -> str:
    """Se o título já existe no banco, devolve variação ' Vol. N' livre; senão devolve o original."""
    import database
    if not database.existe_titulo(titulo, excluir_id=excluir_id, incluir_rascunhos=incluir_rascunhos):
        return titulo
    import re
    base = re.sub(r"\s+Vol\.\s*\d+$", "", titulo, flags=re.IGNORECASE).strip()
    # Famílias de títulos genéricos (ex: kits) podem ter dezenas de volumes ocupados
    for n in range(2, 100):
        candidato = _com_sufixo(base, f" Vol. {n}")
        if not database.existe_titulo(candidato, excluir_id=excluir_id, incluir_rascunhos=incluir_rascunhos):
            return candidato
    return titulo


def validar_anuncio(anuncio: dict, contexto: str = "publicacao") -> tuple:
    """Valida (e auto-corrige quando seguro) um anúncio antes de salvar/publicar.

    Args:
        anuncio: dict com ao menos titulo, preco, tipo; opcionais: id, kit_id,
                 num_exercicios, dificuldade, imagem_path, apostila_id.
        contexto: "criacao" (checa duplicata vs rascunhos+publicados) ou
                  "publicacao" (duplicata fica a cargo de _garantir_titulo_unico).

    Returns:
        (correcoes, corrigidos, bloqueios):
          correcoes: dict campo→novo valor (aplicar no banco/objeto)
          corrigidos: list[str] descrição das correções aplicadas
          bloqueios: list[str] problemas incorrigíveis (não publicar/criar)
    """
    correcoes: dict = {}
    corrigidos: list = []
    bloqueios: list = []

    # --- Título ---------------------------------------------------------
    titulo = (anuncio.get("titulo") or "").strip()
    if not titulo:
        bloqueios.append("título vazio")
    else:
        if titulo != (anuncio.get("titulo") or ""):
            correcoes["titulo"] = titulo
        if len(titulo) > TITULO_MAX:
            titulo = fit_titulo(titulo)
            correcoes["titulo"] = titulo
            corrigidos.append(f"título truncado para {len(titulo)} chars")
        if contexto == "criacao":
            unico = titulo_unico_no_banco(
                titulo, excluir_id=anuncio.get("id"), incluir_rascunhos=True
            )
            if unico != titulo:
                correcoes["titulo"] = unico
                corrigidos.append(f"título duplicado → {unico!r}")

    # --- Preço ----------------------------------------------------------
    tipo = anuncio.get("tipo") or "fisico"
    try:
        preco = float(anuncio.get("preco") or 0)
    except (TypeError, ValueError):
        preco = 0.0
    is_kit = bool(anuncio.get("kit_id"))

    if preco <= 0:
        bloqueios.append(f"preço inválido ({preco})")
    elif is_kit or tipo == "importado":
        # Kit: faixa não se aplica (preço = 0.85×soma, pode passar de 400).
        # Importado: espelho do ML real — nunca auto-corrigir.
        pass
    elif not pricing.preco_na_faixa(tipo, preco):
        canonico = pricing.preco_canonico(
            tipo, anuncio.get("num_exercicios"), anuncio.get("dificuldade")
        )
        if canonico:
            correcoes["preco"] = canonico
            corrigidos.append(f"preço {preco} fora da faixa de {tipo} → {canonico}")
        else:
            bloqueios.append(f"preço {preco} fora da faixa de {tipo} e sem preço de tabela")

    # --- Imagem (só bloqueia se não há como gerar on-demand) -------------
    if contexto == "publicacao":
        if not anuncio.get("imagem_path") and not anuncio.get("apostila_id") and not anuncio.get("kit_id"):
            bloqueios.append("sem imagem e sem apostila/kit para gerar capa on-demand")

    return correcoes, corrigidos, bloqueios
