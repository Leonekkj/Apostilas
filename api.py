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

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database

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
    num_exercicios: int = 60


class KitRequest(BaseModel):
    apostila_ids: list[int]
    nome: Optional[str] = None


# ---------------------------------------------------------------------------
# Static / dashboard
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    # TODO: serve app/index.html once Task 6 creates it
    # from fastapi.responses import FileResponse
    # return FileResponse("app/index.html")
    return {"message": "Dashboard em breve"}


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
    preco = _get_preco(num)

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

        # 5. Update PDF path
        await asyncio.to_thread(database.atualizar_pdf_apostila, apostila_id, pdf_path)

        # 6. Generate 6 ML titles
        titulos = await asyncio.to_thread(content.gerar_titulos_ml, topico, num)

        anuncios_result = []

        # 7. For each of 6 title variants
        for i, title in enumerate(titulos):
            # a. Generate cover image
            image_paths = await asyncio.to_thread(
                images.gerar_capas, apostila_id, topico, num, i
            )
            image_path = image_paths[0] if image_paths else None

            # b. Create anuncio record
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "fisico", i, title["titulo"], preco, i, title.get("angulo", ""),
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
                "variacao": i,
                "imagem_path": image_path,
                "preco": preco,
            })

        return {"apostila_id": apostila_id, "anuncios": anuncios_result}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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

    try:
        # Create kit record
        kit_id = await asyncio.to_thread(database.criar_kit, nome, body.apostila_ids)
        kit = await asyncio.to_thread(database.buscar_kit, kit_id)

        # Total exercicios for pricing
        total_exercicios = sum(ap.get("num_exercicios", 0) for ap in apostilas)

        # Individual price sum * 0.85 discount
        preco_individual = sum(_get_preco(ap.get("num_exercicios", 60)) for ap in apostilas)
        preco_kit = round(preco_individual * 0.85, 2)

        # Generate 6 ML titles for kit
        titulos = await asyncio.to_thread(
            content.gerar_titulos_kit_ml, nome, apostilas, total_exercicios
        )

        anuncios_result = []

        for i, title in enumerate(titulos):
            # Generate kit cover images
            image_paths = await asyncio.to_thread(
                images.gerar_capas_kit, kit_id, nome, apostilas, i
            )
            image_path = image_paths[0] if image_paths else None

            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                None, "fisico", i, title["titulo"], preco_kit, i, title.get("angulo", ""), kit_id,
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        200,          # limite
        0,            # offset
    )
    if apostila_id is not None:
        anuncios = [a for a in anuncios if a.get("apostila_id") == apostila_id]
    return anuncios


@app.post("/api/anuncios/{anuncio_id}/publicar")
async def publicar_anuncio(anuncio_id: int, _auth=Depends(_require_auth)):
    # Phase 2: ML integration not yet implemented
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"error": "Integração ML não configurada ainda"},
    )


@app.post("/api/anuncios/publicar-lote")
async def publicar_lote(_auth=Depends(_require_auth)):
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"error": "Integração ML não configurada ainda"},
    )


@app.delete("/api/anuncios/{anuncio_id}")
async def deletar_anuncio(anuncio_id: int, _auth=Depends(_require_auth)):
    await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, status="deletado")
    return {"deleted": anuncio_id}


# ---------------------------------------------------------------------------
# ML OAuth (no auth required)
# ---------------------------------------------------------------------------

@app.get("/api/ml/status")
async def ml_status():
    tokens = await asyncio.to_thread(database.buscar_ml_tokens)
    if tokens:
        return {"conectado": True, "expires_at": tokens.get("expires_at")}
    return {"conectado": False, "message": "Token ML não configurado"}


@app.get("/api/ml/auth")
async def ml_auth():
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"error": "ML não configurado ainda"},
    )


@app.get("/api/ml/callback")
async def ml_callback():
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"error": "ML não configurado ainda"},
    )


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
