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

# MLB455868 = Ebooks           — exclusão automática por PI
# MLB437616 = Livros Físicos   — exige GTIN/ISBN que apostilas autorais não têm
# MLB445795 = Cursos Completos — ML desativa por "categoria incorreta" (fica em Música/Filmes)
_CATS_BLOQUEADAS = {"MLB455868", "MLB437616", "MLB445795"}

# MLB1726 = Educação e Referência (Informática > Softwares) — aceito pelo ML para apostilas físicas, sem GTIN
# MLB1227 = Outros (Livros, Revistas e Comics) — seguro para digitais sem Ebooks
_FALLBACK_DIG = os.getenv("ML_CATEGORIA_DIGITAL_ID", "MLB1227")
_FALLBACK_FIS = os.getenv("ML_CATEGORIA_FISICO_ID",  "MLB1726")
# Legado: ML_CATEGORIA_ID sobrescreve tudo
_legado = os.getenv("ML_CATEGORIA_ID")


def _safe_cat(cat: str, is_digital: bool) -> str:
    """Garante que a categoria nunca seja uma das bloqueadas (ex: Ebooks)."""
    if cat in _CATS_BLOQUEADAS:
        fallback = _FALLBACK_DIG if is_digital else _FALLBACK_FIS
        print(f"[ML] BLOQUEADO categoria {cat} → usando {fallback}")
        return fallback
    return cat


def _predict_categoria(titulo: str, is_digital: bool) -> str:
    """Consulta ML domain_discovery para obter a categoria ideal para o título.
    Nunca retorna categorias bloqueadas (Ebooks). Usa fallback se predict falhar."""
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
                return _safe_cat(cat, is_digital)
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

    # Truncate title to 60 chars in DB if needed (fix stale titles from before the fix)
    titulo_db = anuncio.get("titulo", "")
    if len(titulo_db) > 60:
        database.atualizar_anuncio(anuncio_id, titulo=titulo_db[:60])

    # 2. Get valid ML token
    try:
        token = auth.get_valid_token()
    except RuntimeError as e:
        raise RuntimeError(f"Token ML não configurado: {e}") from e

    try:
        # 3. Upload até 3 imagens (variação principal + 2 adjacentes)
        imagem_path = anuncio.get("imagem_path") or ""
        print(f"[ML] publicar_anuncio #{anuncio_id}: imagem_path={imagem_path!r}")

        # Se não tiver imagem ou o arquivo não existir mais no disco (filesystem efêmero), gera on-demand
        import storage as _storage
        imagem_ausente = not imagem_path or (not _storage.is_url(imagem_path) and not os.path.exists(imagem_path))
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

        picture_ids = _upload_pictures(token, imagem_path)
        if not picture_ids:
            raise RuntimeError(
                "Nenhuma imagem disponível para upload. "
                "Verifique se a geração de capa está funcionando ou adicione imagens em assets/brand/."
            )
        print(f"[ML] publicar_anuncio #{anuncio_id}: {len(picture_ids)} imagem(ns) enviada(s)")

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
        print(f"[ML] _upload_single: enviando via URL R2 → {imagem_path}")
        response = requests.post(
            ML_PICTURES_ENDPOINT,
            json={"source": imagem_path},
            params={"access_token": token},
        )
    else:
        if not os.path.exists(imagem_path):
            print(f"[ML] _upload_single: arquivo não existe → {imagem_path}")
            return None
        size = os.path.getsize(imagem_path)
        print(f"[ML] _upload_single: enviando arquivo {imagem_path} ({size} bytes)")
        with open(imagem_path, "rb") as f:
            response = requests.post(ML_PICTURES_ENDPOINT, files={"file": f}, params={"access_token": token})

    if response.status_code not in (200, 201):
        print(f"[ML] _upload_single: falhou {response.status_code} → {response.text[:300]}")
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

    # Fallback: capa gerada pelo Pillow + 2 variações adjacentes
    import storage as _storage
    is_url = _storage.is_url(imagem_path)
    if not imagem_path or (not is_url and not os.path.exists(imagem_path)):
        return ids

    main_id = _upload_single(token, imagem_path)
    if main_id:
        ids.append(main_id)

    if not is_url:
        match = re.search(r'_v(\d+)\.png$', imagem_path)
        if match:
            v = int(match.group(1))
            base = imagem_path[:match.start()]
            others = [x for x in [1, 2, 3] if x != v]
            for next_v in others[:2]:
                next_path = f"{base}_v{next_v}.png"
                if os.path.exists(next_path):
                    pid = _upload_single(token, next_path)
                    if pid:
                        ids.append(pid)

    return ids


def _fit_titulo(titulo: str, limit: int = 60) -> str:
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
        "attributes": [
            {"id": "BRAND",                    "value_name": "CogniVita"},
            {"id": "AUTHOR",                   "value_name": "CogniVita"},
            {"id": "LANGUAGE",                 "value_name": "Português"},
            # MLB1726 (Educação e Referência) — obrigatórios
            {"id": "DEVELOPER",                "value_name": "CogniVita"},
            {"id": "EDUCATIONAL_SOFTWARE_NAME","value_name": titulo},
            {"id": "MODEL",                    "value_name": "Apostila Física Impressa"},
            # Qualidade do anúncio — características adicionais
            {"id": "FORMAT",                   "value_id": "2431740" if not is_digital else "2132699",
                                               "value_name": "Físico" if not is_digital else "Digital"},
            {"id": "VERSION",                  "value_name": "1ª Edição"},
            {"id": "WITH_UNLIMITED_LICENSE",   "value_id": "242084", "value_name": "Não"},
        ],
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
    response = requests.post(ML_ITEMS_ENDPOINT, json=payload, headers=headers)
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


def fix_categorias_ml() -> dict:
    """
    Itera todos os anúncios publicados no banco e atualiza a category_id no ML
    para a categoria correta (físico → MLB437616, digital → MLB1227).

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
            print(f"[ML fix-cat] OK {ml_id} → {categoria_correta} ({titulo[:40]})")
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
    me = requests.get(f"{ML_API_BASE}/users/me", headers=headers)
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
        r = requests.get(f"{ML_API_BASE}/items", params={"ids": ids_str}, headers=headers)
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

    response = requests.put(endpoint, json=payload, headers=headers)

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
    response = requests.put(endpoint, json={"price": novo_preco}, headers=headers)
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
    response = requests.put(endpoint, json={"status": "closed"}, headers=headers)

    if response.status_code != 200:
        import logging as _log
        _log.getLogger(__name__).warning(
            "Falha ao fechar anúncio ML %s: %s %s",
            ml_id, response.status_code, response.text[:200]
        )
        return False
    return True
