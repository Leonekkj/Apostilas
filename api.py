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

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import database
from ml import client as ml_client
from ml import orders as ml_orders
from ml import messages as ml_messages

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
# Preços físicos (novos valores)
_PRECOS_PRODUTO = {30: 69.90, 60: 79.90, 90: 89.90, 120: 99.90, 150: 109.90, 200: 119.90}
# Preços digitais (mantidos nos valores anteriores)
_PRECOS_DIGITAL = {30: 16.00, 60: 24.00, 90: 32.00, 120: 40.00, 150: 48.00, 200: 56.00}
_PRECOS_CACA_PALAVRAS = {
    "facil":   14.90,
    "medio":   17.90,
    "dificil": 19.90,
    "gigante": 34.90,
}

_TEMAS_LABEL = {
    "geral":     "para Idosos",
    "futebol":   "de Futebol",
    "culinaria": "de Culinária",
    "animais":   "de Animais",
    "brasil":    "Tema Brasil",
    "musica":    "de Música",
    "natureza":  "de Natureza",
}

_NIVEL_LABEL = {
    "facil":   "Fácil",
    "medio":   "Médio",
    "dificil": "Difícil",
    "gigante": "Gigante",
}


def _titulo_caca_palavras(nome: str, tema: str, dificuldade: str, num_puzzles: int) -> str:
    tema_l  = _TEMAS_LABEL.get(tema, tema.title())
    nivel_l = _NIVEL_LABEL.get(dificuldade, dificuldade.title())
    titulo = f"Caça-Palavras {tema_l} para Idosos — {num_puzzles} Puzzles Nível {nivel_l} | PDF Digital"
    return titulo[:120]


def _descricao_caca_palavras(tema: str, dificuldade: str, num_puzzles: int) -> str:
    tema_l  = _TEMAS_LABEL.get(tema, tema.title())
    nivel_l = _NIVEL_LABEL.get(dificuldade, dificuldade.title())
    linhas = [
        f"✅ {num_puzzles} caça-palavras {tema_l} — Nível {nivel_l}",
        "✅ Gabarito completo incluído no final",
        "✅ PDF digital — receba na hora e imprima em casa",
        "✅ Letra grande e grade espaçada — ideal para idosos 60+",
        "✅ Excelente para estimulação cognitiva e passatempo",
        "",
        "📦 COMO FUNCIONA:",
        "Após a compra você recebe o link para download do PDF. Imprima quantas vezes quiser.",
        "",
        "📐 DIFICULDADE:",
    ]
    desc_dif = {
        "facil":   "Grade 12×12 · 8 palavras por puzzle · Direções horizontal e vertical",
        "medio":   "Grade 15×15 · 12 palavras por puzzle · Inclui diagonal",
        "dificil": "Grade 18×18 · 18 palavras por puzzle · Todas as direções incluindo reverso",
        "gigante": f"300 puzzles em nível médio — o maior volume disponível",
    }
    linhas.append(desc_dif.get(dificuldade, ""))
    linhas += [
        "",
        "🧠 CogniVita — Especialistas em Estimulação Cognitiva para Idosos",
        "cognivita.com.br",
    ]
    return "\n".join(linhas)


def _get_preco(num_exercicios: int) -> float:
    defaults = {30: 69.90, 60: 79.90, 90: 89.90, 120: 99.90, 150: 109.90, 200: 119.90}
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


class CacaPalavrasRequest(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    topico_id: int
    tema: str = Field(default="geral")

# Volumes fixos por dificuldade: (dificuldade, num_puzzles)
_CP_VOLUMES = [
    ("facil",   60),
    ("medio",   60),
    ("dificil", 60),
    ("gigante", 300),
]


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

@app.api_route("/api/health", methods=["GET", "HEAD"])
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

        # Fase 1: v2/v3 compartilhadas (imagens do produto)
        v2_img, v3_img = await asyncio.to_thread(
            images.gerar_imagens_compartilhadas, body.nome, topico, body.serie
        )

        # Fase 2: cria apostilas no DB sem conteúdo (exercícios gerados só após venda)
        apostilas_db = []
        for posicao, num_ex in enumerate(_FATIAS, start=1):
            apostila_id = await asyncio.to_thread(
                database.salvar_apostila, body.topico_id, num_ex, "", produto_id
            )
            created_apostila_ids.append(apostila_id)
            apostilas_db.append((posicao, num_ex, apostila_id))

        # Fase 3: v1 + títulos + descrições tudo em PARALELO (18 tasks simultâneas)
        async def _gen_tudo(apostila_id, num_ex, posicao):
            titulo, descricao, descricao_digital, image_paths = await asyncio.gather(
                asyncio.to_thread(content.gerar_titulo_apostila_produto, body.nome, num_ex),
                asyncio.to_thread(content.gerar_descricao_ml, topico, num_ex),
                asyncio.to_thread(content.gerar_descricao_digital_ml, topico, num_ex),
                asyncio.to_thread(
                    images.gerar_capa_produto,
                    apostila_id, body.nome, topico, num_ex, posicao, body.serie, v2_img, v3_img,
                ),
            )
            return titulo, descricao, descricao_digital, image_paths

        resultados = await asyncio.gather(*[
            _gen_tudo(apostila_id, num_ex, posicao)
            for posicao, num_ex, apostila_id in apostilas_db
        ])
        for _, _, _, image_paths in resultados:
            generated_files.extend(image_paths)

        # Fase 4: cria anúncios físico + digital para cada apostila
        apostilas_result = []
        tabela = body.precos or _PRECOS_PRODUTO
        for (posicao, num_ex, apostila_id), (titulo, descricao, descricao_digital, image_paths) in zip(apostilas_db, resultados):
            image_path = image_paths[0] if image_paths else None
            preco_fisico = float(tabela.get(str(num_ex), tabela.get(num_ex, _PRECOS_PRODUTO.get(num_ex, 29.90))))

            # Anúncio físico
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "fisico", posicao, titulo, preco_fisico, posicao, "", None, descricao,
            )
            created_anuncio_ids.append(anuncio_id)
            if image_path:
                await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, imagem_path=image_path)

            # Anúncio digital — 40% do físico, título limpo + "PDF Digital" (máx 60 chars)
            _remover = ["Apostila Física", "Apostila Fisica", "Impresso", "Impressa", "Físico", "Fisico"]
            titulo_base = titulo
            for palavra in _remover:
                titulo_base = titulo_base.replace(palavra, "").replace("  ", " ").strip()
            sufixo = " PDF Digital"
            max_base = 60 - len(sufixo)
            if len(titulo_base) > max_base:
                titulo_base = titulo_base[:max_base].rsplit(" ", 1)[0]
            titulo_digital = (titulo_base + sufixo)[:60]
            preco_digital = _PRECOS_DIGITAL.get(num_ex, round(preco_fisico * 0.40, 2))
            anuncio_digital_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "digital", posicao, titulo_digital, preco_digital, posicao, "", None, descricao_digital,
            )
            created_anuncio_ids.append(anuncio_digital_id)
            if image_path:
                await asyncio.to_thread(database.atualizar_anuncio, anuncio_digital_id, imagem_path=image_path)

            apostilas_result.append({
                "apostila_id": apostila_id, "num_exercicios": num_ex, "posicao": posicao,
                "preco": preco_fisico, "titulo": titulo, "anuncio_id": anuncio_id,
                "anuncio_digital_id": anuncio_digital_id, "imagem_path": image_path,
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


@app.post("/api/produto/caca-palavras")
async def criar_produto_caca_palavras_endpoint(body: CacaPalavrasRequest, _auth=Depends(_require_auth)):
    """Cria 4 volumes (Fácil/Médio/Difícil/Gigante) de uma vez, com PDF e anúncio por volume."""
    import traceback

    topico = await asyncio.to_thread(database.buscar_topico_por_id, body.topico_id)
    if topico is None:
        raise HTTPException(status_code=404, detail=f"Tópico {body.topico_id} não encontrado")
    if topico.get("slug") != "caca-palavras":
        raise HTTPException(status_code=400, detail="Use o tópico de slug 'caca-palavras'")

    volumes = []
    try:
        from generator import images as gen_images
        topico_cp = {"id": body.topico_id, "nome": "Caça-Palavras", "slug": "caca-palavras"}

        # Fase 1: cria todos os registros no banco (sem gerar PDF)
        registros = []
        for dificuldade, num_puzzles in _CP_VOLUMES:
            nivel_l   = _NIVEL_LABEL.get(dificuldade, dificuldade.title())
            nome_vol  = f"{body.nome} — {nivel_l}"
            preco     = _PRECOS_CACA_PALAVRAS.get(dificuldade, 17.90)
            titulo_ml = _titulo_caca_palavras(nome_vol, body.tema, dificuldade, num_puzzles)
            descricao = _descricao_caca_palavras(body.tema, dificuldade, num_puzzles)

            produto_id = await asyncio.to_thread(
                database.criar_produto_caca_palavras,
                nome_vol, body.topico_id, body.tema, dificuldade,
            )
            apostila_id = await asyncio.to_thread(
                database.salvar_apostila, body.topico_id, num_puzzles, "{}", produto_id
            )
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "digital", 1, titulo_ml, preco, 1, "", None, descricao,
            )
            registros.append((dificuldade, num_puzzles, nome_vol, preco, produto_id, apostila_id, anuncio_id))

        # Fase 2: gera imagens em paralelo para todos os volumes
        async def _gerar_imagem(apostila_id, num_puzzles):
            try:
                # Sem variacao= gera v1, v2 e v3; retorna v1 para imagem_path
                paths = await asyncio.to_thread(gen_images.gerar_capas, apostila_id, topico_cp, num_puzzles)
                return paths[0] if paths else ""
            except Exception:
                return ""

        imagens = await asyncio.gather(*[
            _gerar_imagem(r[5], r[1]) for r in registros
        ])

        # Fase 3: salva imagens e monta resposta
        for (dificuldade, num_puzzles, nome_vol, preco, produto_id, apostila_id, anuncio_id), imagem_path in zip(registros, imagens):
            if imagem_path:
                await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, imagem_path=imagem_path)
            volumes.append({
                "dificuldade": dificuldade,
                "produto_id":  produto_id,
                "apostila_id": apostila_id,
                "anuncio_id":  anuncio_id,
                "preco":       preco,
                "nome":        nome_vol,
            })
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[ERRO caca-palavras] {exc}\n{tb}")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    return {"tema": body.tema, "volumes": volumes}


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


@app.get("/api/shopee/status")
async def shopee_status():
    tokens = await asyncio.to_thread(database.buscar_shopee_tokens)
    if tokens and tokens.get("access_token"):
        return {"conectado": True, "expires_at": tokens.get("expires_at"), "shop_id": tokens.get("shop_id")}
    return {"conectado": False, "message": "Shopee não conectada"}


@app.get("/api/shopee/auth")
async def shopee_auth():
    if not os.getenv("SHOPEE_PARTNER_ID"):
        raise HTTPException(status_code=503, detail="SHOPEE_PARTNER_ID não configurado no servidor")
    from shopee import auth as shopee_auth_module
    url = shopee_auth_module.get_auth_url()
    return {"auth_url": url}


@app.get("/api/shopee/callback")
async def shopee_callback(code: str, shop_id: int):
    try:
        from shopee import auth as shopee_auth_module
        from datetime import datetime, timedelta
        from fastapi.responses import RedirectResponse
        tokens = await asyncio.to_thread(shopee_auth_module.exchange_code, code, shop_id)
        expires_at = (datetime.utcnow() + timedelta(seconds=tokens["expires_in"])).isoformat()
        await asyncio.to_thread(
            database.salvar_shopee_tokens,
            tokens["access_token"], tokens["refresh_token"], expires_at, shop_id,
        )
        return RedirectResponse(url="/?shopee=conectado")
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
# ML Webhook — entrega automática de PDF após pagamento confirmado
# ---------------------------------------------------------------------------

@app.post("/api/ml/webhook")
async def ml_webhook(request: Request):
    """
    Recebe notificações do ML (orders, payments).
    Quando o pagamento é confirmado e o anúncio é digital, envia o PDF ao comprador.
    """
    from fastapi import Request as _Request
    body = await request.json()

    topic = body.get("topic") or body.get("type", "")
    resource = body.get("resource", "")

    # ML envia notificações de vários tópicos — só interessa orders/payments
    if topic not in ("orders", "orders_v2", "payments"):
        return {"status": "ignored", "topic": topic}

    def _processar():
        import requests as _req
        from ml import auth as ml_auth_module

        try:
            token = ml_auth_module.get_valid_token()
        except RuntimeError:
            return {"status": "error", "reason": "token ml não configurado"}

        headers = {"Authorization": f"Bearer {token}"}

        # Resolve o recurso para obter o pedido
        if topic in ("orders", "orders_v2"):
            order_id = resource.strip("/").split("/")[-1]
            r = _req.get(f"https://api.mercadolibre.com/orders/{order_id}", headers=headers, timeout=15)
        else:
            # payment — busca o pedido pelo payment_id
            payment_id = resource.strip("/").split("/")[-1]
            r = _req.get(f"https://api.mercadolibre.com/collections/{payment_id}", headers=headers, timeout=15)
            if r.status_code != 200:
                return {"status": "error", "reason": r.text[:200]}
            order_id = str(r.json().get("collection", {}).get("order_id", ""))
            r = _req.get(f"https://api.mercadolibre.com/orders/{order_id}", headers=headers, timeout=15)

        if r.status_code != 200:
            return {"status": "error", "reason": r.text[:200]}

        pedido = r.json()
        order_status = pedido.get("status", "")
        if order_status != "paid":
            return {"status": "ignored", "order_status": order_status}

        comprador_id = str(pedido.get("buyer", {}).get("id", ""))
        comprador_nick = pedido.get("buyer", {}).get("nickname", "")

        entregues = []
        for item in pedido.get("order_items", []):
            ml_item_id = item.get("item", {}).get("id", "")
            valor = float(item.get("unit_price", 0))
            quantidade = int(item.get("quantity", 1))

            # Registra/atualiza a venda com comprador_id
            anuncio_id = database.buscar_anuncio_id_por_ml_id(ml_item_id)
            database.salvar_venda(
                ml_order_id=order_id,
                anuncio_id=anuncio_id,
                comprador_nickname=comprador_nick,
                valor=valor,
                quantidade=quantidade,
                data_venda=pedido.get("date_created", ""),
                comprador_id=comprador_id,
            )

            # Só entrega PDF se for anúncio digital ainda não entregue
            venda = database.buscar_venda_por_order_id(order_id)
            if not venda or venda.get("pdf_entregue"):
                continue
            if venda.get("anuncio_tipo") != "digital":
                continue

            apostila_id = venda.get("apostila_id")
            if not apostila_id:
                continue

            apostila = database.buscar_apostila_por_id(apostila_id)
            if not apostila:
                continue

            # Gera o PDF se ainda não existir
            pdf_path = apostila.get("pdf_path")
            if not pdf_path or not os.path.exists(pdf_path):
                import logging
                logging.info(f"[webhook] Gerando PDF para apostila {apostila_id} sob demanda...")
                try:
                    is_cp = apostila.get("topico_slug") == "caca-palavras"
                    if is_cp:
                        from gerar_caca_palavras import gerar_pdf_caca_palavras as _gerar_cp
                        tema        = apostila.get("produto_tema") or "geral"
                        dificuldade = apostila.get("produto_dificuldade") or "medio"
                        num_puzzles = apostila.get("num_exercicios") or 60
                        nome_vol    = apostila.get("produto_nome") or "Caça-Palavras"
                        pdf_path = _gerar_cp(apostila_id, nome_vol, tema, dificuldade, num_puzzles)
                        database.salvar_conteudo_apostila(apostila_id, "{}", pdf_path)
                    else:
                        from generator import content as _content, pdf as _gen_pdf
                        topico = {
                            "id": apostila["topico_id"],
                            "nome": apostila.get("topico_nome", ""),
                            "descricao": "",
                        }
                        conteudo_json = _content.gerar_conteudo(topico, apostila["num_exercicios"])
                        pdf_path = _gen_pdf.gerar_pdf(apostila_id, topico, conteudo_json)
                        database.salvar_conteudo_apostila(apostila_id, conteudo_json, pdf_path)
                except Exception as exc:
                    logging.warning(f"[webhook] Falha ao gerar PDF apostila {apostila_id}: {exc}")
                    continue

            app_url = os.getenv("APP_URL", "http://localhost:8000")
            pdf_url = _pdf_path_to_url(pdf_path)
            if not pdf_url:
                continue
            if pdf_url.startswith("/"):
                pdf_url = app_url.rstrip("/") + pdf_url

            nome_apostila = apostila.get("topico_nome", "Apostila Cognitiva CogniVita")
            ok = ml_messages.enviar_pdf_ao_comprador(order_id, comprador_id, pdf_url, nome_apostila)
            if ok:
                database.marcar_pdf_entregue(order_id)
                entregues.append({"order_id": order_id, "apostila_id": apostila_id})

        return {"status": "ok", "entregues": entregues}

    # Responde 200 imediatamente para o ML não reenviar por timeout,
    # e processa a entrega em background
    asyncio.create_task(asyncio.to_thread(_processar))
    return {"status": "received"}


@app.post("/api/admin/anuncios/sincronizar-precos")
async def sincronizar_precos_cognitivo(_auth=Depends(_require_auth)):
    """Aplica preços corretos em todos os anúncios cognitivos publicados no ML:
    - Físicos: novos preços (69.90–119.90)
    - Digitais: preços fixos corretos (16.00–56.00)
    """
    from ml import client as ml_client

    anuncios = await asyncio.to_thread(database.listar_anuncios, status="publicado")
    cognitivos = [
        a for a in anuncios
        if a.get("topico_slug") != "caca-palavras" and a.get("ml_id")
    ]

    atualizados, erros = 0, []
    for a in cognitivos:
        num_ex = a.get("num_exercicios")
        tipo = a.get("tipo", "")
        preco = _PRECOS_PRODUTO.get(num_ex) if tipo == "fisico" else _PRECOS_DIGITAL.get(num_ex)
        if not preco:
            continue
        try:
            await asyncio.to_thread(ml_client.atualizar_preco_ml, a["ml_id"], preco)
            await asyncio.to_thread(database.atualizar_anuncio, a["id"], preco=preco)
            atualizados += 1
        except Exception as e:
            erros.append({"anuncio_id": a["id"], "ml_id": a["ml_id"], "tipo": tipo, "erro": str(e)})

    return {"atualizados": atualizados, "erros": len(erros), "detalhes_erros": erros}


@app.post("/api/admin/anuncios/reverter-precos-digital")
async def reverter_precos_digital(_auth=Depends(_require_auth)):
    """Reverte preços dos anúncios digitais cognitivos para a tabela correta."""
    from ml import client as ml_client

    anuncios = await asyncio.to_thread(database.listar_anuncios, status="publicado")
    digitais = [
        a for a in anuncios
        if a.get("topico_slug") != "caca-palavras"
        and a.get("ml_id")
        and a.get("tipo") == "digital"
    ]

    atualizados, erros = 0, []
    for a in digitais:
        num_ex = a.get("num_exercicios")
        preco_correto = _PRECOS_DIGITAL.get(num_ex)
        if not preco_correto:
            continue
        try:
            await asyncio.to_thread(ml_client.atualizar_preco_ml, a["ml_id"], preco_correto)
            await asyncio.to_thread(database.atualizar_anuncio, a["id"], preco=preco_correto)
            atualizados += 1
        except Exception as e:
            erros.append({"anuncio_id": a["id"], "ml_id": a["ml_id"], "erro": str(e)})

    return {"atualizados": atualizados, "erros": len(erros), "detalhes_erros": erros}


@app.post("/api/admin/anuncios/atualizar-precos-cognitivo")
async def atualizar_precos_cognitivo(_auth=Depends(_require_auth)):
    """Aplica a nova tabela de preços em todos os anúncios cognitivos publicados no ML."""
    from ml import client as ml_client

    novos_precos = _PRECOS_PRODUTO  # {30: 69.90, 60: 79.90, ...}

    anuncios = await asyncio.to_thread(database.listar_anuncios, status="publicado")
    # Apenas anúncios físicos cognitivos (digitais mantêm preço original)
    cognitivos = [
        a for a in anuncios
        if a.get("topico_slug") != "caca-palavras"
        and a.get("ml_id")
        and a.get("tipo") == "fisico"
    ]

    atualizados, erros = 0, []
    for a in cognitivos:
        num_ex = a.get("num_exercicios")
        novo_preco = novos_precos.get(num_ex)
        if not novo_preco:
            continue
        try:
            await asyncio.to_thread(ml_client.atualizar_preco_ml, a["ml_id"], novo_preco)
            await asyncio.to_thread(database.atualizar_anuncio, a["id"], preco=novo_preco)
            atualizados += 1
        except Exception as e:
            erros.append({"anuncio_id": a["id"], "ml_id": a["ml_id"], "erro": str(e)})

    return {
        "atualizados": atualizados,
        "erros": len(erros),
        "detalhes_erros": erros,
    }


@app.post("/api/admin/ml/registrar-webhook")
async def registrar_webhook_ml(_auth=Depends(_require_auth)):
    """Registra o webhook de notificações no ML para este servidor."""
    import requests as _req
    from ml import auth as ml_auth_module

    app_url = os.getenv("APP_URL", "")
    if not app_url:
        raise HTTPException(status_code=400, detail="APP_URL não configurada no servidor")

    webhook_url = app_url.rstrip("/") + "/api/ml/webhook"

    try:
        token = await asyncio.to_thread(ml_auth_module.get_valid_token)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    r = _req.post(
        "https://api.mercadolibre.com/applications/notification_settings",
        json={
            "topics": ["orders_v2"],
            "url": webhook_url,
        },
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )

    if r.status_code in (200, 201):
        return {"registrado": True, "webhook_url": webhook_url, "response": r.json()}
    raise HTTPException(status_code=r.status_code, detail=r.text[:300])


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
