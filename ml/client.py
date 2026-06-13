"""Mercado Livre client for publishing anuncios (listings)."""

import os
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv
load_dotenv()

# Importa modules do diretório pai
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import database
from ml import auth

# Mercado Livre API URLs
ML_API_BASE = "https://api.mercadolibre.com"
ML_PICTURES_ENDPOINT = f"{ML_API_BASE}/pictures"
ML_ITEMS_ENDPOINT = f"{ML_API_BASE}/items"

# MLB455868 = Ebooks                — exclusão automática por PI
# MLB445795 = Cursos Completos      — ML desativa por "categoria incorreta"
# MLB1726   = Informática/Softwares — ML classifica como "Softwares educacionais" -> flagged
# MLB437616 = Livros Físicos — exige GTIN via API (só aceito pelo site ML, não pela API)
_CATS_BLOQUEADAS = {"MLB455868", "MLB445795", "MLB1726", "MLB437616"}

# MLB1227 = Outros (Livros, Revistas e Comics) — sem GTIN, aceito via API para apostilas físicas
_CAT_APOSTILA = os.getenv("ML_CATEGORIA_FISICO_ID", "MLB1227")
_FALLBACK_DIG = os.getenv("ML_CATEGORIA_DIGITAL_ID", "MLB1227")
_FALLBACK_FIS = _CAT_APOSTILA
# Legado: ML_CATEGORIA_ID sobrescreve tudo
_legado = os.getenv("ML_CATEGORIA_ID")

# Whitelist: domain_discovery só é aceito se retornar uma dessas categorias
_CATS_ACEITAS = {
    "MLB1227",    # Outros (Livros, Revistas e Comics) — preferido para apostilas via API
    "MLB48694",   # Livros de Texto e Estudo
}

# Configuração por nicho: o que muda entre públicos-alvo
# genre_id: IDs válidos do ML para BOOK_GENRE em MLB437616
#   7538151 = Infantil | 13061823 = Juvenil | 7538148 = Autoajuda
_NICHE_ATTRS = {
    "idosos":        {"min_age": "60 anos", "genre_id": "7538148",  "genre_name": "Autoajuda"},
    "tdah":          {"min_age": "5 anos",  "genre_id": "7538151",  "genre_name": "Infantil"},
    "autismo":       {"min_age": "3 anos",  "genre_id": "7538151",  "genre_name": "Infantil"},
    "dislexia":      {"min_age": "6 anos",  "genre_id": "7538151",  "genre_name": "Infantil"},
    "avc":           {"min_age": "18 anos", "genre_id": "7538148",  "genre_name": "Autoajuda"},
    "reabilitacao":  {"min_age": "18 anos", "genre_id": "7538148",  "genre_name": "Autoajuda"},
    "cuidadores":    {"min_age": "18 anos", "genre_id": "7538148",  "genre_name": "Autoajuda"},
}

def _niche_config(publico_alvo: str) -> dict:
    """Retorna config de nicho baseada no publico_alvo do topico."""
    pa = publico_alvo.lower()
    for key, cfg in _NICHE_ATTRS.items():
        if key in pa:
            return cfg
    return {"min_age": "18 anos", "genre_id": "7538148", "genre_name": "Autoajuda"}


def _safe_cat(cat: str, is_digital: bool) -> str:
    """Garante que a categoria nunca seja uma das bloqueadas (ex: Ebooks)."""
    if cat in _CATS_BLOQUEADAS:
        fallback = _FALLBACK_DIG if is_digital else _FALLBACK_FIS
        print(f"[ML] BLOQUEADO categoria {cat} -> usando {fallback}")
        return fallback
    return cat


def _predict_categoria(titulo: str, is_digital: bool) -> str:
    """Retorna categoria para o título. Domain_discovery só aceita categorias da whitelist.
    Físico -> MLB271599 (Apostilas e Material Didático). Digital -> MLB1227 (Outros/Livros)."""
    fallback = _FALLBACK_DIG if is_digital else _FALLBACK_FIS

    if _legado:
        return _safe_cat(_legado, is_digital)

    try:
        r = requests.get(
            "https://api.mercadolibre.com/sites/MLB/domain_discovery/search",
            params={"q": titulo},
            timeout=5,
        )
        if r.status_code == 200:
            data = r.json()
            if data:
                cat = data[0]["category_id"]
                # Só aceita se estiver na whitelist — evita categorias de brinquedo, software, etc.
                if cat in _CATS_ACEITAS and cat not in _CATS_BLOQUEADAS:
                    return cat
    except Exception as _e:
        print(f"[ML predict_categoria] falha: {_e}")

    return fallback

# Pasta com imagens reais da marca CogniVita (jpg/jpeg/png, até 3 usadas por listing)
_BRAND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "brand")


def _get_brand_images() -> list[str]:
    """Retorna até 3 caminhos de imagens em assets/brand/, ordenadas por nome."""
    if not os.path.isdir(_BRAND_DIR):
        return []
    exts = {".jpg", ".jpeg", ".png"}
    files = sorted(
        f for f in os.listdir(_BRAND_DIR)
        if os.path.splitext(f)[1].lower() in exts
    )
    return [os.path.join(_BRAND_DIR, f) for f in files[:3]]


def _garantir_titulo_unico(titulo: str, anuncio_id: int) -> str:
    """Garante que nenhum outro anúncio publicado tem o mesmo título, adicionando Vol. N se necessário."""
    import validacao
    candidato = validacao.titulo_unico_no_banco(
        titulo, excluir_id=anuncio_id, incluir_rascunhos=False
    )
    if candidato != titulo:
        print(f"[ML] título duplicado resolvido: {titulo!r} -> {candidato!r}")
    return candidato


def _garantir_imagem_unica(imagem_path: str, anuncio_id: int, anuncio: dict) -> str:
    """Se outro anúncio publicado já usa esta imagem, tenta outra variação ou regenera."""
    if not imagem_path:
        return imagem_path

    import re
    import storage as _storage

    def _count(p: str) -> int:
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute(
                f"SELECT COUNT(*) as cnt FROM anuncios WHERE imagem_path = {database.PH} AND ml_id IS NOT NULL AND status = 'publicado' AND id != {database.PH}",
                [p, anuncio_id],
            )
            row = cur.fetchone()
            return row["cnt"] if isinstance(row, dict) else row[0]

    if _count(imagem_path) == 0:
        return imagem_path

    # Tenta variações _v1 a _v6
    match = re.search(r'_v(\d+)\.(png|jpg)$', imagem_path)
    if match:
        base_path = imagem_path[:match.start()]
        ext = match.group(2)
        current_v = int(match.group(1))
        for v in [1, 2, 3, 4, 5, 6]:
            if v == current_v:
                continue
            candidate = f"{base_path}_v{v}.{ext}"
            if _storage.is_url(candidate):
                try:
                    exists = requests.head(candidate, timeout=4).status_code == 200
                except Exception:
                    exists = False
            else:
                exists = os.path.exists(candidate)
            if exists and _count(candidate) == 0:
                database.atualizar_anuncio(anuncio_id, imagem_path=candidate)
                print(f"[ML] imagem duplicada resolvida: _v{current_v} -> _v{v}")
                return candidate

    # Regenera com próxima paleta
    try:
        from generator import images as _gen_images
        variacao_atual = anuncio.get("variacao") or 1
        nova_variacao = (variacao_atual % 6) + 1
        apostila_id = anuncio.get("apostila_id")
        kit_id = anuncio.get("kit_id")
        if apostila_id:
            topico_dict = {"id": anuncio.get("topico_id"), "nome": anuncio.get("topico_nome", ""), "slug": anuncio.get("topico_slug", "geral")}
            paths = _gen_images.gerar_capas(apostila_id, topico_dict, anuncio.get("num_exercicios") or 60, variacao=nova_variacao)
            if paths and _count(paths[0]) == 0:
                database.atualizar_anuncio(anuncio_id, imagem_path=paths[0])
                print(f"[ML] imagem regenerada paleta {nova_variacao}: {paths[0]}")
                return paths[0]
    except Exception as e:
        print(f"[ML] falha ao regenerar imagem única: {e}")

    return imagem_path


def publicar_anuncio(anuncio_id: int) -> str:
    """
    Publishes a single anuncio to Mercado Livre.

    Args:
        anuncio_id: ID do anúncio no banco de dados.

    Returns:
        str: ML listing ID (ml_id).

    Raises:
        RuntimeError: Se falhar ao publicar ou se dados faltarem.
    """
    # 1. Load anuncio from DB
    anuncio = database.buscar_anuncio_por_id(anuncio_id)
    if anuncio is None:
        raise RuntimeError(f"Anúncio {anuncio_id} não encontrado")

    # Validação central: corrige o seguro (título >60 → corte em palavra),
    # bloqueia o incorrigível (preço <= 0, título vazio) antes de chamar o ML
    import validacao
    correcoes, corrigidos, bloqueios = validacao.validar_anuncio(anuncio, contexto="publicacao")
    if bloqueios:
        msg = "; ".join(bloqueios)
        database.atualizar_anuncio(anuncio_id, status="erro", erro_msg=f"validação: {msg}")
        raise RuntimeError(f"Anúncio {anuncio_id} bloqueado na validação: {msg}")
    if correcoes:
        database.atualizar_anuncio(anuncio_id, **correcoes)
        anuncio.update(correcoes)
        for m in corrigidos:
            print(f"[validacao] publicar_anuncio #{anuncio_id}: {m}")

    # 2. Get valid ML token
    try:
        token = auth.get_valid_token()
    except RuntimeError as e:
        raise RuntimeError(f"Token ML não configurado: {e}") from e

    try:
        # 3. Upload até 3 imagens (variação principal + 2 adjacentes)
        imagem_path = anuncio.get("imagem_path") or ""
        print(f"[ML] publicar_anuncio #{anuncio_id}: imagem_path={imagem_path!r}")

        # Se não tiver imagem ou o arquivo não existir (disco ou R2), gera on-demand
        import storage as _storage
        if not imagem_path:
            imagem_ausente = True
        elif _storage.is_url(imagem_path):
            try:
                imagem_ausente = requests.head(imagem_path, timeout=5).status_code != 200
            except Exception:
                imagem_ausente = True
        else:
            imagem_ausente = not os.path.exists(imagem_path)
        if imagem_ausente and anuncio.get("apostila_id"):
            try:
                from generator import images as _gen_images
                topico_dict = {
                    "id":   anuncio.get("topico_id"),
                    "nome": anuncio.get("topico_nome", ""),
                    "slug": anuncio.get("topico_slug", "geral"),
                }
                num_ex = anuncio.get("num_exercicios") or 60
                print(f"[ML] gerando imagem on-demand: topico={topico_dict['slug']} num_ex={num_ex}")
                paths = _gen_images.gerar_capas(anuncio["apostila_id"], topico_dict, num_ex)
                if paths:
                    imagem_path = paths[0]
                    database.atualizar_anuncio(anuncio_id, imagem_path=imagem_path)
                    print(f"[ML] imagem gerada: {imagem_path}")
                else:
                    print("[ML] gerar_capas retornou lista vazia")
            except Exception as _e:
                print(f"[ML] falha ao gerar imagem on-demand: {_e}")

        elif imagem_ausente and anuncio.get("kit_id"):
            try:
                from generator import images as _gen_images
                kit_id = anuncio["kit_id"]
                kit = database.buscar_kit(kit_id)
                if kit:
                    apostila_ids = kit.get("apostila_ids_list", [])
                    apostilas = [database.buscar_apostila_por_id(aid) for aid in apostila_ids]
                    apostilas = [a for a in apostilas if a]
                    kit_nome = kit.get("nome", anuncio.get("kit_nome", "Kit"))
                    variacao_este = ((anuncio.get("variacao", 1) - 1) % 3) + 1

                    # Gera v1, v2 e v3 de uma vez — os outros anúncios do mesmo kit
                    # já encontrarão as imagens no disco e não precisarão regerar.
                    print(f"[ML] gerando imagens kit on-demand v1/v2/v3: kit_id={kit_id}")
                    all_paths = _gen_images.gerar_capas_kit(kit_id, kit_nome, apostilas)  # sem variacao= gera as 3
                    # Salva cada variacao no anuncio correspondente do mesmo kit
                    kit_anuncios = database.listar_anuncios(kit_id=kit_id, limite=999)
                    for ka in kit_anuncios:
                        v = ((ka.get("variacao", 1) - 1) % 3) + 1
                        for p in all_paths:
                            if f"_v{v}.png" in p:
                                database.atualizar_anuncio(ka["id"], imagem_path=p)
                                break
                    # Imagem deste anúncio
                    for p in all_paths:
                        if f"_v{variacao_este}.png" in p:
                            imagem_path = p
                            break
                    if not imagem_path and all_paths:
                        imagem_path = all_paths[0]
                    print(f"[ML] imagens kit geradas: {all_paths}")
            except Exception as _e:
                print(f"[ML] falha ao gerar imagem kit on-demand: {_e}")

        # Garante unicidade de título e imagem antes de publicar
        titulo_db = anuncio.get("titulo", "")
        titulo_unico = _garantir_titulo_unico(titulo_db, anuncio_id)
        if titulo_unico != titulo_db:
            database.atualizar_anuncio(anuncio_id, titulo=titulo_unico)
            anuncio["titulo"] = titulo_unico

        imagem_path = _garantir_imagem_unica(imagem_path, anuncio_id, anuncio)

        # Garante que v1, v2, v3 existam no R2 (ML exige mínimo 3 imagens)
        import re as _re
        if imagem_path and _storage.is_url(imagem_path):
            match_v = _re.search(r'(_v\d+)(\.png|\.jpg)$', imagem_path, _re.IGNORECASE)
            if match_v and anuncio.get("apostila_id"):
                base_url = imagem_path[:match_v.start()]
                ext = match_v.group(2)
                try:
                    from generator import images as _gen_images
                    import requests as _req
                    topico_dict = {
                        "id":   anuncio.get("topico_id"),
                        "nome": anuncio.get("topico_nome", ""),
                        "slug": anuncio.get("topico_slug", "geral"),
                    }
                    for v in [1, 2, 3]:
                        url_v = f"{base_url}_v{v}{ext}"
                        try:
                            resp = _req.head(url_v, timeout=5)
                            if resp.status_code == 200:
                                continue
                        except Exception:
                            pass
                        print(f"[ML] gerando variacao v{v} e enviando para R2...")
                        paths = _gen_images.gerar_capas(anuncio["apostila_id"], topico_dict,
                                                        anuncio.get("num_exercicios") or 60, variacao=v)
                        if paths:
                            uploaded = _storage.upload(paths[0])
                            print(f"[ML] v{v} enviada para R2: {uploaded}")
                except Exception as _e:
                    print(f"[ML] falha ao garantir 3 variações: {_e}")

        picture_ids = _upload_pictures(token, imagem_path)
        if not picture_ids:
            raise RuntimeError(
                "Nenhuma imagem disponível para upload. "
                "Verifique se a geração de capa está funcionando ou adicione imagens em assets/brand/."
            )
        print(f"[ML] publicar_anuncio #{anuncio_id}: {len(picture_ids)} imagem(ns) enviada(s)")

        # Aguarda ML processar as imagens antes de criar o listing (evita item.pictures.unavailable)
        import time as _time
        _time.sleep(2)

        # 4. Create listing on ML
        ml_id = _create_listing(token, anuncio, picture_ids)

        # 5. Post description (best-effort — não bloqueia se falhar)
        descricao = anuncio.get("descricao", "")
        if descricao and ml_id:
            headers_desc = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            try:
                requests.post(
                    f"{ML_ITEMS_ENDPOINT}/{ml_id}/description",
                    json={"plain_text": descricao},
                    headers=headers_desc,
                    timeout=15,
                )
            except Exception:
                pass

        # 6. Update anuncio with success
        now = datetime.utcnow().isoformat()
        database.atualizar_anuncio(
            anuncio_id,
            ml_id=ml_id,
            status="publicado",
            publicado_em=now,
        )

        return ml_id

    except RuntimeError as e:
        # 7. Update anuncio with error
        database.atualizar_anuncio(
            anuncio_id,
            status="erro",
            erro_msg=str(e),
        )
        raise


def _upload_single(token: str, imagem_path: str) -> Optional[str]:
    """Faz upload de uma imagem e retorna o picture_id, ou None se falhar.
    Se imagem_path for URL (R2), envia via JSON — ML baixa diretamente do R2 sem usar bandwidth do Render.
    """
    if not imagem_path:
        print("[ML] _upload_single: imagem_path é None/vazio")
        return None

    import storage as _storage
    if _storage.is_url(imagem_path):
        print(f"[ML] _upload_single: enviando via URL R2 -> {imagem_path}")
        response = requests.post(
            ML_PICTURES_ENDPOINT,
            json={"source": imagem_path},
            params={"access_token": token},
            timeout=30,
        )
    else:
        if not os.path.exists(imagem_path):
            print(f"[ML] _upload_single: arquivo não existe -> {imagem_path}")
            return None
        size = os.path.getsize(imagem_path)
        print(f"[ML] _upload_single: enviando arquivo {imagem_path} ({size} bytes)")
        with open(imagem_path, "rb") as f:
            response = requests.post(ML_PICTURES_ENDPOINT, files={"file": f}, params={"access_token": token}, timeout=60)

    if response.status_code not in (200, 201):
        print(f"[ML] _upload_single: falhou {response.status_code} -> {response.text[:300]}")
        return None
    pid = response.json().get("id")
    print(f"[ML] _upload_single: OK picture_id={pid}")
    return pid


def _upload_pictures(token: str, imagem_path: str) -> list[str]:
    """
    Faz upload de imagens para o ML. Prioriza imagens reais de assets/brand/;
    caso a pasta esteja vazia, usa a capa Pillow + até 2 variações adjacentes.
    Retorna lista de picture_ids (1 a 3 itens).
    """
    import re
    ids = []

    # Imagens reais da marca têm prioridade
    brand = _get_brand_images()
    if brand:
        for path in brand:
            pid = _upload_single(token, path)
            if pid:
                ids.append(pid)
        return ids

    # Capa gerada pelo Pillow: sempre tenta carregar v1, v2, v3 (mínimo 3 imagens para ML)
    import storage as _storage
    is_url = _storage.is_url(imagem_path)
    if not imagem_path or (not is_url and not os.path.exists(imagem_path)):
        return ids

    # Constrói lista de todas as variações a partir do path/URL da imagem principal
    match = re.search(r'(_v\d+)(\.png|\.jpg)$', imagem_path, re.IGNORECASE)
    if match:
        base = imagem_path[:match.start()]
        ext = match.group(2)
        # Ordena para que a variação original venha primeiro
        current_v = int(re.search(r'\d+', match.group(1)).group())
        all_vs = [current_v] + [v for v in [1, 2, 3] if v != current_v]
        candidates = [f"{base}_v{v}{ext}" for v in all_vs]
    else:
        candidates = [imagem_path]

    for path in candidates:
        if len(ids) >= 3:
            break
        # Verifica existência de cada candidato individualmente
        if _storage.is_url(path):
            try:
                path_exists = requests.head(path, timeout=4).status_code == 200
            except Exception:
                path_exists = False
        else:
            path_exists = os.path.exists(path)
        if path_exists:
            pid = _upload_single(token, path)
            if pid:
                ids.append(pid)

    return ids


# Movido para validacao.py (fonte única). Alias preserva referências existentes.
from validacao import fit_titulo as _fit_titulo


def _create_listing(token: str, anuncio: dict, picture_ids: list[str]) -> str:
    """
    Creates a listing on Mercado Livre.

    Args:
        token: Access token do ML.
        anuncio: Dicionário com dados do anúncio (titulo, preco, topico_nome, etc).
        picture_id: ID da imagem (opcional).

    Returns:
        str: ML listing ID (ml_id).

    Raises:
        RuntimeError: Se falhar ao criar listing.
    """
    titulo = _fit_titulo(anuncio.get("titulo", "Apostila Cognitiva"))
    is_digital = anuncio.get("tipo", "fisico") == "digital"
    categoria_id = _predict_categoria(titulo, is_digital)
    # Barreira final — nunca deixa Ebooks chegar ao payload
    categoria_id = _safe_cat(categoria_id, is_digital)
    print(f"[ML] categoria selecionada: {categoria_id} (titulo={titulo[:50]!r})")
    # Persiste a categoria efetivamente enviada — permite auditoria posterior
    if anuncio.get("id"):
        try:
            database.atualizar_anuncio(anuncio["id"], categoria_id=categoria_id)
        except Exception as _e:
            print(f"[ML] falha ao persistir categoria_id: {_e}")

    # Busca publico_alvo e colecao do topico para atributos dinâmicos
    topico_id = anuncio.get("topico_id")
    publico_alvo = "adultos"
    colecao = "CogniVita"
    if topico_id:
        try:
            topico = database.buscar_topico_por_id(topico_id)
            if topico:
                publico_alvo = topico.get("publico_alvo") or publico_alvo
                colecao = topico.get("colecao") or colecao
        except Exception as _e:
            print(f"[ML] falha ao buscar topico {topico_id}: {_e}")

    niche = _niche_config(publico_alvo)
    ano = "2026"

    # Atributos de livro — compatíveis com MLB1227 (Outros/Livros) e MLB437616
    attributes = [
        {"id": "BRAND",                        "value_name": "CogniVita"},
        {"id": "TITLE",                        "value_name": titulo},
        {"id": "BOOK_TITLE",                   "value_name": titulo},
        {"id": "AUTHOR",                       "value_name": "CogniVita"},
        {"id": "PUBLISHER",                    "value_name": "CogniVita"},
        {"id": "BOOK_PUBLISHER",               "value_name": "CogniVita"},
        {"id": "LANGUAGE",                     "value_name": "Português"},
        {"id": "BOOK_EDITION",                 "value_name": ano},
        {"id": "BOOK_COVER",                   "value_name": "Mole"},
        {"id": "BOOK_COVER_MATERIAL",          "value_name": "Papel cartão mole"},
        {"id": "BOOK_VOLUME",                  "value_name": ano},
        {"id": "BOOK_SERIE",                   "value_name": ano},
        {"id": "BOOK_VERSION",                 "value_name": ano},
        {"id": "BOOK_COLLECTION",              "value_name": colecao},
        {"id": "PUBLICATION_YEAR",             "value_name": ano},
        {"id": "PAGES_NUMBER",                 "value_name": str(anuncio.get("num_exercicios") or 60)},
        {"id": "MIN_RECOMMENDED_AGE",          "value_name": niche["min_age"]},
        {"id": "BOOK_GENRE",                   "value_id": niche["genre_id"], "value_name": niche["genre_name"]},
        {"id": "IS_WRITTEN_IN_CAPITAL_LETTERS","value_name": "Sim"},
        {"id": "WITH_COLORING_PAGES",          "value_name": "Não"},
        {"id": "WITH_AUGMENTED_REALITY",       "value_name": "Não"},
    ]

    # Build item payload
    payload = {
        "title": titulo,
        "category_id": categoria_id,
        "price": float(anuncio.get("preco", 0)),
        "currency_id": "BRL",
        "available_quantity": 999,
        "buying_mode": "buy_it_now",
        "listing_type_id": "gold_pro",
        "condition": "new",
        "attributes": attributes,
    }

    if is_digital:
        payload["shipping"] = {
            "mode": "not_specified",
            "free_shipping": True,
            "local_pick_up": False,
        }
    else:
        payload["shipping"] = {
            "mode": "me2",
            "free_shipping": True,
            "local_pick_up": False,
        }

    # Até 3 imagens
    if picture_ids:
        payload["pictures"] = [{"id": pid} for pid in picture_ids]

    # Make request
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    import json as _json
    print("[ML] PAYLOAD listing_type_id:", payload.get("listing_type_id"))
    response = requests.post(ML_ITEMS_ENDPOINT, json=payload, headers=headers, timeout=30)
    print("[ML] RESPONSE status:", response.status_code)
    print("[ML] RESPONSE body:", response.text[:2000])

    if response.status_code != 201:
        try:
            error_data = response.json()
            error_msg = str(error_data)
        except Exception:
            error_msg = response.text
        raise RuntimeError(f"ML API error {response.status_code}: {error_msg}")

    data = response.json()
    returned_type = data.get("listing_type_id", "unknown")
    if returned_type != "gold_pro":
        print(
            f"[ML] AVISO: ML retornou listing_type_id='{returned_type}' em vez de 'gold_pro'. "
            "Verifique se a conta ML tem o plano Premium ativo."
        )
    else:
        print(f"[ML] OK: listing criado como Premium (gold_pro): {data.get('id')}")
    return data.get("id")


def obter_imagem_anuncio(ml_id: str) -> Optional[str]:
    """URL da foto principal do anúncio publicado (CDN do ML), em alta resolução.

    Fonte da verdade para 'capa do PDF = foto do anúncio'. Retorna None se o
    item não existir, não tiver fotos ou a API falhar (caller usa fallback).
    """
    if not ml_id:
        return None
    try:
        token = auth.get_valid_token()
        r = requests.get(
            f"{ML_API_BASE}/items/{ml_id}",
            params={"attributes": "pictures"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        pics = r.json().get("pictures") or []
        if not pics:
            return None
        return pics[0].get("secure_url") or pics[0].get("url")
    except Exception as e:
        print(f"[ML] obter_imagem_anuncio({ml_id}) falhou: {e}")
        return None


def fix_categorias_ml() -> dict:
    """
    Itera todos os anúncios publicados no banco e atualiza a category_id no ML
    para a categoria correta (físico -> MLB437616, digital -> MLB1227).

    Returns:
        dict com listas 'atualizados', 'erros', 'sem_ml_id'.
    """
    token = auth.get_valid_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    anuncios = database.listar_anuncios(status="publicado", limite=9999)
    atualizados = []
    erros = []
    sem_ml_id = []

    for an in anuncios:
        ml_id = an.get("ml_id")
        if not ml_id:
            sem_ml_id.append(an.get("id"))
            continue

        is_digital = an.get("tipo", "fisico") == "digital"
        titulo = an.get("titulo", "")
        categoria_correta = _predict_categoria(titulo, is_digital)

        r = requests.put(
            f"{ML_ITEMS_ENDPOINT}/{ml_id}",
            json={"category_id": categoria_correta},
            headers=headers,
            timeout=15,
        )
        if r.status_code == 200:
            atualizados.append({"anuncio_id": an["id"], "ml_id": ml_id, "categoria": categoria_correta})
            print(f"[ML fix-cat] OK {ml_id} -> {categoria_correta} ({titulo[:40]})")
        else:
            erros.append({"anuncio_id": an["id"], "ml_id": ml_id, "status": r.status_code, "detail": r.text[:300]})
            print(f"[ML fix-cat] ERRO {ml_id}: {r.status_code} {r.text[:200]}")

    return {
        "atualizados": len(atualizados),
        "erros": len(erros),
        "sem_ml_id": len(sem_ml_id),
        "detalhes_erros": erros,
    }


def importar_anuncios_ml() -> list[dict]:
    """
    Busca todos os anúncios ativos do vendedor no ML e importa para o banco.

    Returns:
        Lista de dicts com os anúncios importados.
    """
    token = auth.get_valid_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Pega o user_id do vendedor
    me = requests.get(f"{ML_API_BASE}/users/me", headers=headers, timeout=15)
    if me.status_code != 200:
        raise RuntimeError(f"Erro ao buscar dados do usuário: {me.text}")
    user_id = me.json()["id"]

    # 2. Busca todos os item IDs (paginado)
    item_ids = []
    offset = 0
    while True:
        r = requests.get(
            f"{ML_API_BASE}/users/{user_id}/items/search",
            params={"offset": offset, "limit": 50},
            headers=headers,
            timeout=15,
        )
        if r.status_code != 200:
            break
        data = r.json()
        results = data.get("results", [])
        item_ids.extend(results)
        if len(results) < 50:
            break
        offset += 50

    if not item_ids:
        return []

    # 3. Busca detalhes em lote (máx 20 por chamada)
    importados = []
    for i in range(0, len(item_ids), 20):
        batch = item_ids[i:i+20]
        ids_str = ",".join(batch)
        r = requests.get(f"{ML_API_BASE}/items", params={"ids": ids_str}, headers=headers, timeout=15)
        if r.status_code != 200:
            continue
        for entry in r.json():
            item = entry.get("body", {})
            if not item:
                continue
            ml_id = item.get("id", "")
            titulo = item.get("title", "")
            preco = float(item.get("price", 0))
            status_ml = item.get("status", "active")
            status_local = "publicado" if status_ml == "active" else "pausado"
            thumbnail = ""
            pics = item.get("pictures", [])
            if pics:
                thumbnail = pics[0].get("url", "")
            db_id = database.importar_anuncio_externo(ml_id, titulo, preco, status_local, thumbnail)
            importados.append({"id": db_id, "ml_id": ml_id, "titulo": titulo, "preco": preco, "status": status_local})

    return importados


def pausar_anuncio(anuncio_id: int) -> None:
    """
    Pauses an active ML listing.

    Args:
        anuncio_id: ID do anúncio no banco de dados.

    Raises:
        RuntimeError: Se falhar ao pausar.
    """
    # Load anuncio
    anuncio = database.buscar_anuncio_por_id(anuncio_id)
    if anuncio is None:
        raise RuntimeError(f"Anúncio {anuncio_id} não encontrado")

    ml_id = anuncio.get("ml_id")
    if not ml_id:
        raise RuntimeError(f"Anúncio {anuncio_id} não tem ml_id (não foi publicado)")

    # Get valid token
    try:
        token = auth.get_valid_token()
    except RuntimeError as e:
        raise RuntimeError(f"Token ML não configurado: {e}") from e

    # Pause on ML
    endpoint = f"{ML_ITEMS_ENDPOINT}/{ml_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"status": "paused"}

    response = requests.put(endpoint, json=payload, headers=headers, timeout=15)

    if response.status_code != 200:
        error_data = response.json()
        error_msg = error_data.get("message", response.text)
        raise RuntimeError(f"ML API error {response.status_code}: {error_msg}")

    # Update status locally
    database.atualizar_anuncio(anuncio_id, status="pausado")


def atualizar_preco_ml(ml_id: str, novo_preco: float) -> None:
    """Atualiza o preço de um anúncio publicado no ML."""
    token = auth.get_valid_token()
    endpoint = f"{ML_ITEMS_ENDPOINT}/{ml_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    response = requests.put(endpoint, json={"price": novo_preco}, headers=headers, timeout=15)
    if response.status_code != 200:
        error_msg = response.json().get("message", response.text)
        raise RuntimeError(f"ML API error {response.status_code}: {error_msg}")


def fechar_anuncio_ml(ml_id: str) -> bool:
    """Closes an ML listing permanently. Returns True on success, False on failure (non-blocking)."""
    if not ml_id:
        return False
    try:
        token = auth.get_valid_token()
    except RuntimeError:
        return False

    endpoint = f"{ML_ITEMS_ENDPOINT}/{ml_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.put(endpoint, json={"status": "closed"}, headers=headers, timeout=15)

    if response.status_code != 200:
        import logging as _log
        _log.getLogger(__name__).warning(
            "Falha ao fechar anúncio ML %s: %s %s",
            ml_id, response.status_code, response.text[:200]
        )
        return False
    return True
