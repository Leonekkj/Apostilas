"""FastAPI application — Apostilas ML dashboard.

Endpoints:
  GET  /                        → placeholder (TODO: serve app/index.html once Task 6 is done)
  GET  /api/health              → {"status": "ok"}
  GET  /api/topicos             → active topics
  GET  /api/stats               → anuncio counts + product/kit counts
  GET  /api/produtos            → list products (apostilas)
  GET  /api/kits                → list kits
  GET  /api/anuncios            → list anuncios (?status= ?apostila_id=)
  POST /api/produto             → generate produto + 6 anuncios (blocking, asyncio.to_thread)
  POST /api/kit                 → generate kit + 6 anuncios
  POST /api/anuncios/{id}/publicar   → 501 (Phase 2)
  POST /api/anuncios/publicar-lote   → 501 (Phase 2)
  DELETE /api/anuncios/{id}    → mark status='deletado'
  GET  /api/ml/status          → ML connection status
  GET  /api/ml/auth            → 501 (Phase 2)
  GET  /api/ml/callback        → 501 (Phase 2)
"""

import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import database
from ml import client as ml_client
from ml import orders as ml_orders

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Apostilas ML", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated images / PDFs at /output/<filename>
_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(_OUTPUT_DIR, exist_ok=True)
app.mount("/output", StaticFiles(directory=_OUTPUT_DIR), name="output")


def _pdf_path_to_url(pdf_path: str) -> str | None:
    """Converte filesystem path do PDF em URL relativa com cache-busting."""
    if not pdf_path:
        return None
    try:
        rel = os.path.relpath(pdf_path, os.path.dirname(os.path.abspath(__file__)))
        url = "/" + rel.replace("\\", "/")
        if os.path.exists(pdf_path):
            url += f"?v={int(os.path.getmtime(pdf_path))}"
        return url
    except ValueError:
        return None


@app.on_event("startup")
async def on_startup() -> None:
    await asyncio.to_thread(database.criar_tabelas)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def _require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ADMIN_TOKEN não configurado no servidor",
        )
    if credentials is None or credentials.credentials != ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Price table
# ---------------------------------------------------------------------------

_FATIAS = [30, 60, 90, 120, 150, 200]
_PRECOS_PRODUTO = {30: 14.90, 60: 19.90, 90: 24.90, 120: 29.90, 150: 34.90, 200: 44.90}


def _get_preco(num_exercicios: int) -> float:
    defaults = {30: 14.90, 60: 29.90, 90: 34.90, 120: 39.90, 150: 44.90, 200: 44.90}
    env_key = f"PRECO_{num_exercicios}"
    raw = os.getenv(env_key)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return defaults.get(num_exercicios, 29.90)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ProdutoRequest(BaseModel):
    topico_id: int
    num_exercicios: int = Field(default=60, ge=1, le=150)
    preco: Optional[float] = None


class ProdutoLinhaRequest(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    topico_id: int
    serie: int = Field(default=1, ge=1, le=99)
    precos: Optional[dict] = None  # {30: 14.90, 60: 19.90, ...} — sobrescreve _PRECOS_PRODUTO


class KitRequest(BaseModel):
    apostila_ids: list[int]
    nome: Optional[str] = None


class AnuncioUpdate(BaseModel):
    preco: Optional[float] = None
    titulo: Optional[str] = None


class LinkApostilaBody(BaseModel):
    apostila_id: Optional[int]


class AnuncioGerarPdfRequest(BaseModel):
    topico_id: int
    num_exercicios: int = Field(..., ge=1, le=200)


# ---------------------------------------------------------------------------
# Static / dashboard
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "index.html")
    return FileResponse(html_path)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tópicos
# ---------------------------------------------------------------------------

@app.get("/api/topicos")
async def listar_topicos(_auth=Depends(_require_auth)):
    topicos = await asyncio.to_thread(database.listar_topicos)
    return topicos


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@app.get("/api/stats")
async def stats(_auth=Depends(_require_auth)):
    contagem = await asyncio.to_thread(database.contar_anuncios)
    produtos = await asyncio.to_thread(database.listar_produtos_com_apostilas)
    kits = await asyncio.to_thread(database.listar_kits)
    return {
        "anuncios": contagem,
        "total_produtos": len(produtos),
        "total_kits": len(kits),
    }


# ---------------------------------------------------------------------------
# Produtos (apostilas)
# ---------------------------------------------------------------------------

@app.get("/api/produtos")
async def listar_produtos(_auth=Depends(_require_auth)):
    return await asyncio.to_thread(database.listar_produtos_com_apostilas)


@app.post("/api/produto")
async def criar_produto_linha(body: ProdutoLinhaRequest, _auth=Depends(_require_auth)):
    from generator import content, images

    topico = await asyncio.to_thread(database.buscar_topico_por_id, body.topico_id)
    if topico is None:
        raise HTTPException(status_code=404, detail=f"Tópico {body.topico_id} não encontrado")

    generated_files = []
    created_apostila_ids = []
    created_anuncio_ids = []
    produto_id = None
    try:
        produto_id = await asyncio.to_thread(database.criar_produto, body.nome, body.topico_id, body.serie)
        conteudo_200_json = await asyncio.to_thread(content.gerar_conteudo, topico, 200)

        # Gera v2 e v3 UMA VEZ para o produto (compartilhado entre apostilas)
        v2_img, v3_img = await asyncio.to_thread(
            images.gerar_imagens_compartilhadas, body.nome, topico, body.serie
        )

        # Fase 1: cria todas as apostilas no banco e gera títulos/descrições
        apostilas_db = []
        for posicao, num_ex in enumerate(_FATIAS, start=1):
            conteudo_fatia = await asyncio.to_thread(content.fatiar_conteudo, conteudo_200_json, num_ex)
            apostila_id = await asyncio.to_thread(
                database.salvar_apostila, body.topico_id, num_ex, conteudo_fatia, produto_id
            )
            created_apostila_ids.append(apostila_id)
            titulo = await asyncio.to_thread(content.gerar_titulo_apostila_produto, body.nome, num_ex)
            descricao = await asyncio.to_thread(content.gerar_descricao_ml, topico, num_ex)
            apostilas_db.append((posicao, num_ex, apostila_id, titulo, descricao))

        # Fase 2: gera V1 de todas as apostilas EM PARALELO
        async def _gerar_v1(apostila_id, num_ex, posicao):
            return await asyncio.to_thread(
                images.gerar_capa_produto,
                apostila_id, body.nome, topico, num_ex, posicao, body.serie, v2_img, v3_img,
            )

        all_image_paths = await asyncio.gather(*[
            _gerar_v1(apostila_id, num_ex, posicao)
            for posicao, num_ex, apostila_id, _, _ in apostilas_db
        ])
        for paths in all_image_paths:
            generated_files.extend(paths)

        # Fase 3: cria anúncios e vincula imagens
        apostilas_result = []
        tabela = body.precos or _PRECOS_PRODUTO
        for (posicao, num_ex, apostila_id, titulo, descricao), image_paths in zip(apostilas_db, all_image_paths):
            image_path = image_paths[0] if image_paths else None
            preco = float(tabela.get(str(num_ex), tabela.get(num_ex, _PRECOS_PRODUTO.get(num_ex, 29.90))))
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "fisico", posicao, titulo, preco, posicao, "", None, descricao,
            )
            created_anuncio_ids.append(anuncio_id)
            if image_path:
                await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, imagem_path=image_path)
            apostilas_result.append({
                "apostila_id": apostila_id, "num_exercicios": num_ex, "posicao": posicao,
                "preco": preco, "titulo": titulo, "anuncio_id": anuncio_id, "imagem_path": image_path,
            })

        return {"produto_id": produto_id, "nome": body.nome, "serie": body.serie, "apostilas": apostilas_result}

    except Exception as exc:
        for fpath in generated_files:
            try:
                os.remove(fpath)
            except OSError:
                pass
        for apid in created_apostila_ids:
            try:
                await asyncio.to_thread(database.deletar_apostila, apid)
            except Exception:
                pass
        if produto_id:
            try:
                await asyncio.to_thread(database.deletar_produto, produto_id)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Erro ao gerar produto: {exc}") from exc


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------

@app.get("/api/kits")
async def listar_kits(_auth=Depends(_require_auth)):
    return await asyncio.to_thread(database.listar_kits)


@app.post("/api/kit")
async def criar_kit(body: KitRequest, _auth=Depends(_require_auth)):
    from generator import content, images

    if not body.apostila_ids:
        raise HTTPException(status_code=400, detail="apostila_ids não pode ser vazio")

    # Load each apostila
    apostilas = []
    for aid in body.apostila_ids:
        ap = await asyncio.to_thread(database.buscar_apostila_por_id, aid)
        if ap is None:
            raise HTTPException(status_code=404, detail=f"Apostila {aid} não encontrada")
        apostilas.append(ap)

    # Resolve kit name
    nome = body.nome
    if not nome:
        nome = await asyncio.to_thread(content.sugerir_nome_kit, apostilas)

    generated_files: list[str] = []
    try:
        # Create kit record
        kit_id = await asyncio.to_thread(database.criar_kit, nome, body.apostila_ids)

        # Total exercicios for pricing
        total_exercicios = sum(ap.get("num_exercicios", 0) for ap in apostilas)

        # Individual price sum * 0.85 discount
        preco_individual = sum(_get_preco(ap.get("num_exercicios", 60)) for ap in apostilas)
        preco_kit = round(preco_individual * 0.85, 2)

        # Generate 6 ML titles + description for kit
        titulos = await asyncio.to_thread(
            content.gerar_titulos_kit_ml, nome, apostilas, total_exercicios
        )
        topico_kit = {"nome": nome}
        descricao_kit = await asyncio.to_thread(content.gerar_descricao_ml, topico_kit, total_exercicios)

        anuncios_result = []

        for i, title in enumerate(titulos, start=1):
            # Generate kit cover images
            image_paths = await asyncio.to_thread(
                images.gerar_capas_kit, kit_id, nome, apostilas, i
            )
            generated_files.extend(image_paths)
            image_path = image_paths[0] if image_paths else None

            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                None, "fisico", i, title["titulo"], preco_kit, i, title.get("angulo", ""), kit_id,
                descricao_kit,
            )

            if image_path:
                await asyncio.to_thread(
                    database.atualizar_anuncio, anuncio_id, imagem_path=image_path
                )

            anuncios_result.append({
                "anuncio_id": anuncio_id,
                "titulo": title["titulo"],
                "angulo": title.get("angulo", ""),
                "variacao": i,
                "imagem_path": image_path,
                "preco": preco_kit,
            })

        return {"kit_id": kit_id, "nome": nome, "anuncios": anuncios_result}

    except HTTPException:
        raise
    except Exception as exc:
        for fpath in generated_files:
            try:
                os.remove(fpath)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Erro ao gerar kit: {exc}") from exc


# ---------------------------------------------------------------------------
# Anúncios
# ---------------------------------------------------------------------------

@app.get("/api/anuncios")
async def listar_anuncios(
    status: Optional[str] = None,
    apostila_id: Optional[int] = None,
    _auth=Depends(_require_auth),
):
    anuncios = await asyncio.to_thread(
        database.listar_anuncios,
        status,       # status filter
        None,         # tipo
        None,         # topico_id
        None,         # kit_id
        apostila_id,  # apostila_id filter
        200,          # limite
        0,            # offset
    )
    return anuncios


@app.post("/api/anuncios/{anuncio_id}/publicar")
async def publicar_anuncio(anuncio_id: int, _auth=Depends(_require_auth)):
    try:
        ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, anuncio_id)
        return {"ml_id": ml_id, "message": "Publicado com sucesso"}
    except RuntimeError as e:
        error_msg = str(e)
        if "não configurado" in error_msg.lower() or "token" in error_msg.lower():
            raise HTTPException(status_code=503, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@app.post("/api/anuncios/publicar-lote")
async def publicar_lote(_auth=Depends(_require_auth)):
    rascunhos = await asyncio.to_thread(database.buscar_anuncios_rascunho, 30)
    results = []
    for anuncio in rascunhos:
        try:
            ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, anuncio["id"])
            results.append({"id": anuncio["id"], "ml_id": ml_id, "status": "publicado"})
        except RuntimeError as e:
            results.append({"id": anuncio["id"], "error": str(e), "status": "erro"})
    return {
        "publicados": len([r for r in results if r["status"] == "publicado"]),
        "resultados": results
    }


@app.delete("/api/anuncios/{anuncio_id}")
async def deletar_anuncio(anuncio_id: int, _auth=Depends(_require_auth)):
    anuncio = await asyncio.to_thread(database.buscar_anuncio_por_id, anuncio_id)
    if anuncio and anuncio.get("ml_id"):
        await asyncio.to_thread(ml_client.fechar_anuncio_ml, anuncio["ml_id"])
    await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, status="deletado")
    return {"deleted": anuncio_id}


@app.delete("/api/produto/{produto_id}")
async def deletar_produto(produto_id: int, _auth=Depends(_require_auth)):
    apostilas = await asyncio.to_thread(database.listar_apostilas_por_produto, produto_id)
    ml_fechados = 0
    for ap in apostilas:
        anuncios = await asyncio.to_thread(database.listar_anuncios, apostila_id=ap["id"])
        for an in anuncios:
            if an.get("ml_id"):
                ok = await asyncio.to_thread(ml_client.fechar_anuncio_ml, an["ml_id"])
                if ok:
                    ml_fechados += 1
            await asyncio.to_thread(database.atualizar_anuncio, an["id"], status="deletado")
    await asyncio.to_thread(database.deletar_produto, produto_id)
    return {"deleted": produto_id, "ml_fechados": ml_fechados}


@app.delete("/api/kit/{kit_id}")
async def deletar_kit_endpoint(kit_id: int, _auth=Depends(_require_auth)):
    ml_ids = await asyncio.to_thread(database.deletar_anuncios_por_kit, kit_id)
    ml_fechados = 0
    for ml_id in ml_ids:
        ok = await asyncio.to_thread(ml_client.fechar_anuncio_ml, ml_id)
        if ok:
            ml_fechados += 1
    await asyncio.to_thread(database.deletar_kit, kit_id)
    return {"deleted": kit_id, "ml_fechados": ml_fechados}


@app.patch("/api/anuncios/{anuncio_id}")
async def atualizar_anuncio_endpoint(anuncio_id: int, body: AnuncioUpdate, _auth=Depends(_require_auth)):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, **updates)
    return {"updated": anuncio_id}


# ---------------------------------------------------------------------------
# Admin: Apostilas
# ---------------------------------------------------------------------------

@app.get("/api/admin/apostilas")
async def listar_apostilas_admin(auth=Depends(_require_auth)):
    return await asyncio.to_thread(database.listar_todas_apostilas)


@app.get("/api/admin/apostilas/{apostila_id}")
async def buscar_apostila_admin(apostila_id: int, _auth=Depends(_require_auth)):
    apostila = await asyncio.to_thread(database.buscar_apostila_por_id, apostila_id)
    if apostila is None:
        raise HTTPException(status_code=404, detail=f"Apostila {apostila_id} não encontrada")
    pdf_path = apostila.get("pdf_path")
    pdf_url = _pdf_path_to_url(pdf_path) if pdf_path and os.path.exists(pdf_path) else None
    return {
        "id": apostila["id"],
        "topico_nome": apostila.get("topico_nome", ""),
        "num_exercicios": apostila["num_exercicios"],
        "pdf_url": pdf_url,
    }


@app.post("/api/admin/apostilas/{apostila_id}/gerar-pdf")
async def gerar_pdf_apostila(apostila_id: int, _auth=Depends(_require_auth)):
    from generator import content, pdf as gen_pdf

    apostila = await asyncio.to_thread(database.buscar_apostila_por_id, apostila_id)
    if apostila is None:
        raise HTTPException(status_code=404, detail=f"Apostila {apostila_id} não encontrada")

    # Cache: se o arquivo já existe no disco, devolve sem regerar
    cached_path = apostila.get("pdf_path")
    if cached_path and os.path.exists(cached_path):
        return {"pdf_url": _pdf_path_to_url(cached_path), "cached": True}

    # Monta dict de tópico compatível com gerar_conteudo()
    topico = {
        "id": apostila["topico_id"],
        "nome": apostila.get("topico_nome", ""),
        "descricao": "",
    }
    num_exercicios = apostila["num_exercicios"]

    try:
        conteudo_json = await asyncio.to_thread(content.gerar_conteudo, topico, num_exercicios)
        pdf_path = await asyncio.to_thread(gen_pdf.gerar_pdf, apostila_id, topico, conteudo_json)
        await asyncio.to_thread(
            database.salvar_conteudo_apostila, apostila_id, conteudo_json, pdf_path
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar PDF: {exc}") from exc

    return {"pdf_url": _pdf_path_to_url(pdf_path), "cached": False}


@app.post("/api/admin/anuncios/{anuncio_id}/gerar-pdf")
async def gerar_pdf_anuncio(
    anuncio_id: int,
    body: AnuncioGerarPdfRequest,
    _auth=Depends(_require_auth),
):
    from generator import content, pdf as gen_pdf

    anuncio = await asyncio.to_thread(database.buscar_anuncio_por_id, anuncio_id)
    if anuncio is None:
        raise HTTPException(status_code=404, detail=f"Anúncio {anuncio_id} não encontrado")

    # Idempotência: se já vinculado e PDF no disco, devolve cached
    existing_apostila_id = anuncio.get("apostila_id")
    if existing_apostila_id:
        cached_path = anuncio.get("pdf_path")
        if cached_path and os.path.exists(cached_path):
            return {
                "pdf_url": _pdf_path_to_url(cached_path),
                "apostila_id": existing_apostila_id,
                "cached": True,
            }

    topico = await asyncio.to_thread(database.buscar_topico_por_id, body.topico_id)
    if topico is None:
        raise HTTPException(status_code=404, detail=f"Tópico {body.topico_id} não encontrado")

    try:
        apostila_id = await asyncio.to_thread(
            database.salvar_apostila, body.topico_id, body.num_exercicios, ""
        )
        await asyncio.to_thread(
            database.atualizar_anuncio, anuncio_id, apostila_id=apostila_id
        )
        conteudo_json = await asyncio.to_thread(
            content.gerar_conteudo, topico, body.num_exercicios
        )
        pdf_path = await asyncio.to_thread(
            gen_pdf.gerar_pdf, apostila_id, topico, conteudo_json
        )
        await asyncio.to_thread(
            database.salvar_conteudo_apostila, apostila_id, conteudo_json, pdf_path
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar PDF: {exc}") from exc

    return {
        "pdf_url": _pdf_path_to_url(pdf_path),
        "apostila_id": apostila_id,
        "cached": False,
    }


# ---------------------------------------------------------------------------
# Admin: Link apostila to anuncio
# ---------------------------------------------------------------------------

@app.patch("/api/admin/anuncios/{anuncio_id}/apostila")
async def linkar_apostila_anuncio(
    anuncio_id: int,
    body: LinkApostilaBody,
    auth=Depends(_require_auth),
):
    await asyncio.to_thread(
        database.atualizar_anuncio, anuncio_id, apostila_id=body.apostila_id
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin: Vendas
# ---------------------------------------------------------------------------

@app.post("/api/admin/vendas/sincronizar")
async def sincronizar_vendas(auth=Depends(_require_auth)):
    from datetime import datetime

    def _sync():
        pedidos = ml_orders.buscar_pedidos_pagos()
        importados = 0
        for pedido in pedidos:
            ml_order_id = str(pedido.get("id", ""))
            if not ml_order_id:
                continue
            comprador_nickname = pedido.get("buyer", {}).get("nickname", "")
            data_venda = pedido.get("date_created", "")
            for item in pedido.get("order_items", []):
                ml_item_id = item.get("item", {}).get("id", "")
                valor = float(item.get("unit_price", 0))
                quantidade = int(item.get("quantity", 1))
                anuncio_id = database.buscar_anuncio_id_por_ml_id(ml_item_id)
                database.salvar_venda(
                    ml_order_id=ml_order_id,
                    anuncio_id=anuncio_id,
                    comprador_nickname=comprador_nickname,
                    valor=valor,
                    quantidade=quantidade,
                    data_venda=data_venda,
                )
                importados += 1
        return importados

    importados = await asyncio.to_thread(_sync)
    return {
        "importados": importados,
        "ultima_sincronizacao": datetime.utcnow().isoformat(),
    }


@app.get("/api/admin/vendas/resumo")
async def resumo_vendas(auth=Depends(_require_auth)):
    return await asyncio.to_thread(database.resumo_vendas_por_apostila)


@app.get("/api/admin/vendas")
async def listar_vendas(
    apostila_id: Optional[int] = None,
    anuncio_id: Optional[int] = None,
    sem_apostila: bool = False,
    auth=Depends(_require_auth),
):
    return await asyncio.to_thread(
        database.listar_vendas, apostila_id, anuncio_id, sem_apostila
    )


# ---------------------------------------------------------------------------
# ML OAuth (no auth required)
# ---------------------------------------------------------------------------

@app.post("/api/ml/importar")
async def importar_do_ml(_auth=Depends(_require_auth)):
    try:
        importados = await asyncio.to_thread(ml_client.importar_anuncios_ml)
        return {"importados": len(importados), "anuncios": importados}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/ml/status")
async def ml_status():
    tokens = await asyncio.to_thread(database.buscar_ml_tokens)
    if tokens:
        return {"conectado": True, "expires_at": tokens.get("expires_at")}
    return {"conectado": False, "message": "Token ML não configurado"}


@app.get("/api/ml/auth")
async def ml_auth():
    if not os.getenv("ML_CLIENT_ID"):
        raise HTTPException(status_code=503, detail="ML_CLIENT_ID não configurado no servidor")
    from ml import auth as ml_auth_module
    url = ml_auth_module.get_auth_url()
    return {"auth_url": url}


@app.get("/api/ml/callback")
async def ml_callback(code: str):
    try:
        from ml import auth as ml_auth_module
        from datetime import datetime, timedelta
        from fastapi.responses import RedirectResponse
        tokens = await asyncio.to_thread(ml_auth_module.exchange_code, code)
        expires_at = (datetime.utcnow() + timedelta(seconds=tokens["expires_in"])).isoformat()
        await asyncio.to_thread(database.salvar_ml_tokens,
            tokens["access_token"], tokens["refresh_token"], expires_at)
        return RedirectResponse(url="/?ml=conectado")
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ml/listing-types")
async def ml_listing_types():
    """Retorna os tipos de anúncio disponíveis para o vendedor na categoria configurada."""
    import requests as _req
    from ml import auth as ml_auth_module
    try:
        token = await asyncio.to_thread(ml_auth_module.get_valid_token)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    cat_id = os.getenv("ML_CATEGORIA_ID", "MLB1196")
    headers = {"Authorization": f"Bearer {token}"}

    # Busca tipos de anúncio disponíveis para o vendedor
    r = await asyncio.to_thread(
        lambda: _req.get(
            f"https://api.mercadolibre.com/users/me/listing_types",
            headers=headers,
        )
    )
    seller_types = r.json() if r.status_code == 200 else {"error": r.text}

    # Busca tipos disponíveis para a categoria
    r2 = await asyncio.to_thread(
        lambda: _req.get(
            f"https://api.mercadolibre.com/categories/{cat_id}/listing_types",
            headers=headers,
        )
    )
    cat_types = r2.json() if r2.status_code == 200 else {"error": r2.text}

    return {
        "categoria": cat_id,
        "tipos_vendedor": seller_types,
        "tipos_categoria": cat_types,
    }


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
