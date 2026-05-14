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

def _get_preco(num_exercicios: int) -> float:
    defaults = {60: 29.90, 90: 34.90, 120: 39.90, 150: 44.90}
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


class KitRequest(BaseModel):
    apostila_ids: list[int]
    nome: Optional[str] = None


class AnuncioUpdate(BaseModel):
    preco: Optional[float] = None
    titulo: Optional[str] = None


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
    produtos = await asyncio.to_thread(database.listar_produtos)
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
    return await asyncio.to_thread(database.listar_produtos)


@app.post("/api/produto")
async def criar_produto(body: ProdutoRequest, _auth=Depends(_require_auth)):
    from generator import content, images, pdf

    # 1. Validate topico
    topico = await asyncio.to_thread(database.buscar_topico_por_id, body.topico_id)
    if topico is None:
        raise HTTPException(status_code=404, detail=f"Tópico {body.topico_id} não encontrado")

    num = body.num_exercicios
    preco = body.preco if body.preco is not None else _get_preco(num)

    generated_files: list[str] = []
    try:
        # 2. Generate content
        conteudo_json = await asyncio.to_thread(
            content.gerar_conteudo, topico, num
        )

        # 3. Save apostila
        apostila_id = await asyncio.to_thread(
            database.salvar_apostila, body.topico_id, num, conteudo_json
        )

        # 4. Generate PDF
        pdf_path = await asyncio.to_thread(
            pdf.gerar_pdf, apostila_id, topico, conteudo_json
        )
        generated_files.append(pdf_path)

        # 5. Update PDF path
        await asyncio.to_thread(database.atualizar_pdf_apostila, apostila_id, pdf_path)

        # 6. Generate 6 ML titles + description
        titulos = await asyncio.to_thread(content.gerar_titulos_ml, topico, num)
        descricao = await asyncio.to_thread(content.gerar_descricao_ml, topico, num)

        anuncios_result = []

        # 7. For each of 6 title variants
        for i, title in enumerate(titulos):
            variacao = i + 1  # paletas vão de 1 a 6
            # a. Generate cover image
            image_paths = await asyncio.to_thread(
                images.gerar_capas, apostila_id, topico, num, variacao
            )
            generated_files.extend(image_paths)
            image_path = image_paths[0] if image_paths else None

            # b. Create anuncio record
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "fisico", variacao, title["titulo"], preco, variacao, title.get("angulo", ""),
                None, descricao,
            )

            # c. Update image path
            if image_path:
                await asyncio.to_thread(
                    database.atualizar_anuncio, anuncio_id, imagem_path=image_path
                )

            anuncios_result.append({
                "anuncio_id": anuncio_id,
                "titulo": title["titulo"],
                "angulo": title.get("angulo", ""),
                "variacao": variacao,
                "imagem_path": image_path,
                "preco": preco,
            })

        return {"apostila_id": apostila_id, "anuncios": anuncios_result}

    except Exception as exc:
        for fpath in generated_files:
            try:
                os.remove(fpath)
            except OSError:
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

        for i, title in enumerate(titulos):
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


@app.patch("/api/anuncios/{anuncio_id}")
async def atualizar_anuncio_endpoint(anuncio_id: int, body: AnuncioUpdate, _auth=Depends(_require_auth)):
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, **updates)
    return {"updated": anuncio_id}


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


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
