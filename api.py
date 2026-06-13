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
import json
import os
import secrets as _secrets
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Security, status
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


_scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def on_startup() -> None:
    await asyncio.to_thread(database.criar_tabelas)
    # Fixes diários: 3h da manhã (horário servidor = UTC)
    _scheduler.add_job(_fix_titulos_bg, "cron", hour=3, minute=0, id="fix_titulos")
    # REGRA DE NEGÓCIO: produto digital é PROIBIDO no ML (já causou suspensão).
    # O job fix_cp_digital (convertia caça-palavras → digital) foi DESATIVADO.
    _scheduler.add_job(_fix_imagens_pillow_bg, "cron", hour=4, minute=0, id="fix_imagens")
    _scheduler.start()
    print("[scheduler] Jobs diários registrados: fix_titulos, fix_imagens")


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
    if credentials is None or not _secrets.compare_digest(credentials.credentials, ADMIN_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Price table — fonte única em pricing.py
# ---------------------------------------------------------------------------

import pricing
from pricing import (
    FATIAS as _FATIAS,
    PRECOS_PRODUTO as _PRECOS_PRODUTO,
    PRECOS_DIGITAL as _PRECOS_DIGITAL,
    PRECOS_CACA_PALAVRAS as _PRECOS_CACA_PALAVRAS,
)

_TEMAS_LABEL = {
    "geral":     "para Idosos",
    "futebol":   "de Futebol",
    "culinaria": "de Culinária",
    "animais":   "de Animais",
    "brasil":    "Tema Brasil",
    "musica":    "de Música",
    "natureza":  "de Natureza",
}

# Rótulo compacto (sem preposição) para uso no título ML de 60 chars
_TEMAS_CURTO = {
    "geral":     "",
    "futebol":   "Futebol",
    "culinaria": "Culinária",
    "animais":   "Animais",
    "brasil":    "Brasil",
    "musica":    "Música",
    "natureza":  "Natureza",
}

_NIVEL_LABEL = {
    "facil":   "Fácil",
    "medio":   "Médio",
    "dificil": "Difícil",
    "gigante": "Gigante",
}


def _titulo_caca_palavras(nome: str, tema: str, dificuldade: str, num_puzzles: int) -> str:
    """Gera título ≤60 chars para caça-palavras FÍSICO (digital é proibido no ML)."""
    nivel_l = _NIVEL_LABEL.get(dificuldade, dificuldade.title())
    tema_c  = _TEMAS_CURTO.get(tema, tema.title())

    if tema_c:
        # Ex: "Caça-Palavras Futebol 60 Puzzles Nível Difícil Impresso"
        titulo = f"Caça-Palavras {tema_c} {num_puzzles} Puzzles Nível {nivel_l} Impresso"
    else:
        # Ex: "Caça-Palavras 300 Puzzles Nível Gigante Idosos Impresso"
        titulo = f"Caça-Palavras {num_puzzles} Puzzles Nível {nivel_l} Idosos Impresso"

    # Segurança: truncar na última palavra
    if len(titulo) > 60:
        titulo = titulo[:60].rsplit(" ", 1)[0]

    return titulo


def _descricao_caca_palavras(tema: str, dificuldade: str, num_puzzles: int) -> str:
    tema_l  = _TEMAS_LABEL.get(tema, tema.title())
    nivel_l = _NIVEL_LABEL.get(dificuldade, dificuldade.title())

    _spec = {
        "facil": (
            "Grade 12×12 · 8 palavras por puzzle",
            "Direções horizontal e vertical — ideal para iniciantes",
            "Perfeito para quem está começando ou prefere um ritmo mais tranquilo.",
        ),
        "medio": (
            "Grade 15×15 · 12 palavras por puzzle",
            "Direções horizontal, vertical e diagonal",
            "Equilibra desafio e prazer — o nível mais procurado.",
        ),
        "dificil": (
            "Grade 18×18 · 18 palavras por puzzle",
            "Todas as direções incluindo reverso",
            "Máximo de estimulação — para quem quer um desafio real.",
        ),
        "gigante": (
            f"{num_puzzles} puzzles em nível médio",
            "O maior volume disponível — meses de atividade garantidos",
            "Ideal para clínicas, cuidadores e quem usa diariamente.",
        ),
    }
    grade, direcoes, frase_dif = _spec.get(dificuldade, ("", "", ""))

    return "\n".join([
        f"CAÇA-PALAVRAS {tema_l.upper()} — PDF DIGITAL PARA IDOSOS",
        "",
        f"Coleção com {num_puzzles} caça-palavras {tema_l}, nível {nivel_l}. "
        f"{frase_dif} "
        "Letra grande, grade espaçada e gabarito completo incluído — tudo pensado para idosos 60+.",
        "",
        "O QUE VOCÊ RECEBE",
        f"• {num_puzzles} caça-palavras {tema_l} em PDF",
        f"• Nível {nivel_l}: {grade}",
        f"• {direcoes}",
        "• Gabarito completo no final do arquivo",
        "• Fonte ampliada — ideal para leitura confortável",
        "",
        "COMO FUNCIONA",
        "• Compre e receba o PDF na hora por mensagem no Mercado Livre",
        "• Imprima em casa (A4, preto e branco) quantas vezes quiser",
        "• Comece a usar no mesmo dia — sem esperar entrega",
        "",
        "BENEFÍCIOS",
        "• Estimula memória, atenção e raciocínio de forma lúdica",
        "• Atividade comprovada para manutenção da saúde cognitiva",
        "• Passatempo saudável e prazeroso para a terceira idade",
        "• Gabarito incluso para autonomia e autoconfiança",
        "",
        "ESPECIFICAÇÕES",
        "• Formato: PDF Digital",
        f"• Quantidade: {num_puzzles} puzzles",
        f"• Nível: {nivel_l} ({grade})",
        "• Páginas: A4 — Impressão recomendada: Preto e Branco",
        "• Fonte ampliada (ideal para idosos 60+)",
        "",
        "🧠 CogniVita — Especialistas em Estimulação Cognitiva para Idosos",
        "cognivita.com.br",
    ])


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
# Helpers internos
# ---------------------------------------------------------------------------

async def _publicar_anuncios(anuncio_ids: list) -> dict:
    """Publica uma lista de anúncios no ML com 0.3s de pausa entre cada um.
    Retorna {'publicados': [...ml_id], 'erros': [{anuncio_id, erro}]}."""
    publicados = []
    erros = []
    for aid in anuncio_ids:
        try:
            anuncio = await asyncio.to_thread(database.buscar_anuncio_por_id, aid)
            if not anuncio:
                continue
            if anuncio.get("ml_id"):
                continue
            if anuncio.get("erro_msg") and "validation_error" in str(anuncio.get("erro_msg", "")):
                erros.append({"anuncio_id": aid, "erro": anuncio["erro_msg"]})
                continue
            ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, aid)
            publicados.append({"anuncio_id": aid, "ml_id": ml_id})
        except Exception as e:
            erros.append({"anuncio_id": aid, "erro": str(e)})
        await asyncio.sleep(0.3)
    return {"publicados": publicados, "erros": erros}


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

        # Fase 4: cria apenas anúncio físico por apostila (sem digital)
        apostilas_result = []
        tabela = body.precos or _PRECOS_PRODUTO
        for (posicao, num_ex, apostila_id), (titulo, descricao, descricao_digital, image_paths) in zip(apostilas_db, resultados):
            image_path = image_paths[0] if image_paths else None
            if image_path:
                import storage as _storage
                image_path = await asyncio.to_thread(_storage.upload, image_path)
            preco_fisico = float(tabela.get(str(num_ex), tabela.get(num_ex, _PRECOS_PRODUTO.get(num_ex, 29.90))))

            # Anúncio físico apenas
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "fisico", posicao, titulo, preco_fisico, posicao, "", None, descricao,
            )
            created_anuncio_ids.append(anuncio_id)
            if image_path:
                await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, imagem_path=image_path)

            apostilas_result.append({
                "apostila_id": apostila_id, "num_exercicios": num_ex, "posicao": posicao,
                "preco": preco_fisico, "titulo": titulo, "anuncio_id": anuncio_id,
                "imagem_path": image_path,
            })

        # Publica todos os anúncios imediatamente após criação
        pub_result = await _publicar_anuncios(created_anuncio_ids)
        # Preenche ml_id nos apostilas_result para o response
        ml_id_map = {p["anuncio_id"]: p["ml_id"] for p in pub_result["publicados"]}
        for ap in apostilas_result:
            ap["ml_id"] = ml_id_map.get(ap["anuncio_id"])

        return {
            "produto_id": produto_id,
            "nome": body.nome,
            "serie": body.serie,
            "apostilas": apostilas_result,
            "publicados": len(pub_result["publicados"]),
            "erros_publicacao": pub_result["erros"],
        }

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
    pub_result: dict = {"publicados": [], "erros": []}
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
            # REGRA: digital é proibido no ML — caça-palavras é FÍSICO impresso
            anuncio_id = await asyncio.to_thread(
                database.criar_anuncio,
                apostila_id, "fisico", 1, titulo_ml, preco, 1, "", None, descricao,
            )
            registros.append((dificuldade, num_puzzles, nome_vol, preco, produto_id, apostila_id, anuncio_id))

        # Fase 2: gera imagens em paralelo para todos os volumes
        async def _gerar_imagem(apostila_id, num_puzzles):
            try:
                # Sem variacao= gera v1, v2 e v3; retorna v1 para imagem_path
                paths = await asyncio.to_thread(gen_images.gerar_capas, apostila_id, topico_cp, num_puzzles)
                return paths[0] if paths else ""
            except Exception as _img_err:
                print(f"[WARN caca-palavras] falha ao gerar imagem apostila_id={apostila_id}: {_img_err}")
                return ""

        imagens = await asyncio.gather(*[
            _gerar_imagem(r[5], r[1]) for r in registros
        ])

        # Fase 3: salva imagens e monta resposta
        import storage as _storage
        anuncio_ids_cp = []
        for (dificuldade, num_puzzles, nome_vol, preco, produto_id, apostila_id, anuncio_id), imagem_path in zip(registros, imagens):
            if imagem_path:
                imagem_path = await asyncio.to_thread(_storage.upload, imagem_path)
                await asyncio.to_thread(database.atualizar_anuncio, anuncio_id, imagem_path=imagem_path)
            volumes.append({
                "dificuldade": dificuldade,
                "produto_id":  produto_id,
                "apostila_id": apostila_id,
                "anuncio_id":  anuncio_id,
                "preco":       preco,
                "nome":        nome_vol,
            })
            anuncio_ids_cp.append(anuncio_id)

        # Fase 4: publica todos os anúncios imediatamente
        pub_result = await _publicar_anuncios(anuncio_ids_cp)
        ml_id_map = {p["anuncio_id"]: p["ml_id"] for p in pub_result["publicados"]}
        for v in volumes:
            v["ml_id"] = ml_id_map.get(v["anuncio_id"])

    except Exception as exc:
        tb = traceback.format_exc()
        print(f"[ERRO caca-palavras] {exc}\n{tb}")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    return {
        "tema": body.tema,
        "volumes": volumes,
        "publicados": len(pub_result["publicados"]),
        "erros_publicacao": pub_result["erros"],
    }


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

        # Total exercicios for pricing and titles
        total_exercicios = sum(ap.get("num_exercicios", 0) for ap in apostilas)

        # Preço: usa o preço real do anúncio físico existente de cada apostila.
        # Fallback para _PRECOS_PRODUTO quando a apostila ainda não tem anúncio.
        async def _preco_apostila(ap: dict) -> float:
            # Busca qualquer tipo de anúncio (fisico, importado) ligado à apostila
            anuncios = await asyncio.to_thread(
                database.listar_anuncios, None, None, None, None, ap["id"], 1
            )
            # Filtra anúncios com preço real (>50) de apostila individual
            for an in anuncios:
                p = float(an.get("preco") or 0)
                if p > 50 and not an.get("kit_id"):
                    return p
            return _PRECOS_PRODUTO.get(ap.get("num_exercicios", 60), 79.99)

        precos = await asyncio.gather(*[_preco_apostila(ap) for ap in apostilas])
        preco_individual = sum(precos)
        preco_kit = pricing.preco_kit(preco_individual)

        # Generate 6 ML titles + description for kit
        titulos = await asyncio.to_thread(
            content.gerar_titulos_kit_ml, nome, apostilas, total_exercicios
        )
        descricao_kit = await asyncio.to_thread(
            content.gerar_descricao_kit_ml, nome, apostilas, total_exercicios
        )

        anuncios_result = []

        for i, title in enumerate(titulos, start=1):
            variacao_img = ((i - 1) % 3) + 1
            # Generate kit cover images
            image_paths = await asyncio.to_thread(
                images.gerar_capas_kit, kit_id, nome, apostilas, variacao_img
            )
            generated_files.extend(image_paths)
            image_path = image_paths[0] if image_paths else None
            if image_path:
                import storage as _storage
                image_path = await asyncio.to_thread(_storage.upload, image_path)

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

        # Publica todos os anúncios do kit imediatamente
        publicados = []
        erros_pub = []
        for item in anuncios_result:
            aid = item["anuncio_id"]
            try:
                ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, aid)
                item["ml_id"] = ml_id
                item["status"] = "publicado"
                publicados.append(aid)
            except Exception as pub_e:
                item["status"] = "erro"
                item["erro_pub"] = str(pub_e)
                erros_pub.append({"anuncio_id": aid, "erro": str(pub_e)})
            await asyncio.sleep(0.3)

        return {
            "kit_id": kit_id,
            "nome": nome,
            "anuncios": anuncios_result,
            "publicados": len(publicados),
            "erros_publicacao": erros_pub,
        }

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
    page: int = 1,
    per_page: int = 50,
    _auth=Depends(_require_auth),
):
    page = max(1, page)
    per_page = min(max(1, per_page), 200)
    offset = (page - 1) * per_page

    anuncios, total = await asyncio.gather(
        asyncio.to_thread(database.listar_anuncios, status, None, None, None, apostila_id, per_page, offset),
        asyncio.to_thread(database.contar_anuncios_filtrado, status, None, None, None, apostila_id),
    )
    import math
    return {
        "items": anuncios,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, math.ceil(total / per_page)),
    }


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


@app.post("/api/admin/gerar-e-publicar/{topico_id}")
async def gerar_e_publicar(
    topico_id: int,
    quantidade: int = 3,
    _auth=Depends(_require_auth),
):
    """Cria `quantidade` produtos para o tópico, gera kits (duplo/triplo/completo) e publica tudo."""
    topico = await asyncio.to_thread(database.buscar_topico_por_id, topico_id)
    if topico is None:
        raise HTTPException(status_code=404, detail=f"Tópico {topico_id} não encontrado")

    # Descobre próxima série disponível
    def _proxima_serie() -> int:
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute(
                f"SELECT COALESCE(MAX(serie), 0) + 1 AS proxima FROM produtos WHERE topico_id = {database.PH}",
                [topico_id],
            )
            row = cur.fetchone()
            return int(row["proxima"] if isinstance(row, dict) else row[0])

    proxima = await asyncio.to_thread(_proxima_serie)

    resumo_produtos = []
    todas_apostilas: list[dict] = []  # acumula apostilas de todos os produtos

    # ── 1. Cria produtos e publica anúncios individuais ──────────────────────
    for i in range(quantidade):
        serie = proxima + i
        nome = f"{topico['nome']} CogniVita"
        body = ProdutoLinhaRequest(nome=nome, topico_id=topico_id, serie=serie)
        resultado = await criar_produto_linha(body, _auth=_auth)
        resumo_produtos.append({
            "produto_id": resultado["produto_id"],
            "serie": serie,
            "publicados": resultado.get("publicados", 0),
        })
        # Coleta apostilas criadas (tem apostila_id no resultado)
        for ap in resultado.get("apostilas", []):
            ap["serie"] = serie
            todas_apostilas.append(ap)

    # ── 2. Para cada produto, cria 3 kits e publica ───────────────────────────
    # Apostilas por série: {serie: {num_ex: apostila_id}}
    por_serie: dict[int, dict[int, int]] = {}
    for ap in todas_apostilas:
        por_serie.setdefault(ap["serie"], {})[ap["num_exercicios"]] = ap["apostila_id"]

    resumo_kits = []
    combos = {
        "Duplo":    [60, 90],
        "Triplo":   [90, 120, 150],
        "Completo": [30, 60, 90, 120, 150, 200],
    }

    for serie, ex_map in por_serie.items():
        for tipo_kit, exercicios in combos.items():
            ids_kit = [ex_map[ex] for ex in exercicios if ex in ex_map]
            if len(ids_kit) < 2:
                continue
            kit_nome = f"{topico['nome']} Kit {tipo_kit} Vol. {serie}"
            kit_body = KitRequest(apostila_ids=ids_kit, nome=kit_nome)
            kit_resultado = await criar_kit(kit_body, _auth=_auth)
            resumo_kits.append({
                "kit_id": kit_resultado["kit_id"],
                "tipo": tipo_kit,
                "serie": serie,
                "publicados": len([a for a in kit_resultado.get("anuncios", []) if a.get("status") == "publicado"]),
            })

    return {
        "topico": topico["nome"],
        "produtos_criados": len(resumo_produtos),
        "kits_criados": len(resumo_kits),
        "resumo_produtos": resumo_produtos,
        "resumo_kits": resumo_kits,
    }


@app.post("/api/admin/publicar-kits")
async def publicar_kits(_auth=Depends(_require_auth), limite: int = 30):
    """Publica até `limite` anúncios de kit com status rascunho/erro.
    Gera imagens on-demand se necessário. Pausa 5s entre publicações."""
    anuncios = await asyncio.to_thread(
        database.listar_anuncios, "rascunho", "fisico", None, None, None, limite, 0
    )
    kit_anuncios = [a for a in anuncios if a.get("kit_id")]

    # Complementa com anuncios de kit com status erro, exceto os com validation_error
    # (esses precisam de correção manual, não de re-tentativa infinita)
    if len(kit_anuncios) < limite:
        erros = await asyncio.to_thread(
            database.listar_anuncios, "erro", "fisico", None, None, None, limite * 3, 0
        )
        for a in erros:
            if not a.get("kit_id"):
                continue
            erro_msg = a.get("erro_msg") or ""
            if "validation_error" in erro_msg:
                continue
            kit_anuncios.append(a)
            if len(kit_anuncios) >= limite:
                break

    results = []
    for anuncio in kit_anuncios:
        try:
            ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, anuncio["id"])
            results.append({"id": anuncio["id"], "kit_id": anuncio["kit_id"], "ml_id": ml_id, "status": "publicado"})
        except RuntimeError as e:
            results.append({"id": anuncio["id"], "kit_id": anuncio["kit_id"], "error": str(e), "status": "erro"})
        await asyncio.sleep(5)

    return {
        "total": len(kit_anuncios),
        "publicados": len([r for r in results if r["status"] == "publicado"]),
        "erros": len([r for r in results if r["status"] == "erro"]),
        "resultados": results,
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


@app.delete("/api/admin/anuncios/inativos")
async def deletar_anuncios_inativos(_auth=Depends(_require_auth)):
    """Marca como 'deletado' todos os anúncios que não estão publicados (rascunho, erro, pausado)."""
    def _buscar_inativos():
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute(
                "SELECT id, ml_id FROM anuncios WHERE status NOT IN ('publicado', 'deletado')"
            )
            return database._rows_to_dicts(cur.fetchall(), cur)

    rows = await asyncio.to_thread(_buscar_inativos)

    ml_fechados = 0
    for row in rows:
        if row.get("ml_id"):
            ok = await asyncio.to_thread(ml_client.fechar_anuncio_ml, row["ml_id"])
            if ok:
                ml_fechados += 1
        await asyncio.to_thread(database.atualizar_anuncio, row["id"], status="deletado")

    return {"deletados": len(rows), "ml_fechados": ml_fechados}


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


@app.post("/api/admin/fix-cp-tema-dificuldade")
async def fix_cp_tema_dificuldade(_auth=Depends(_require_auth)):
    """Backfill colunas tema/dificuldade em produtos CP que têm NULL (criados antes das colunas existirem)."""
    _TEMA_MAP = {
        "futebol": "futebol", "animais": "animais", "brasil": "brasil",
        "música": "musica", "musica": "musica", "culinária": "culinaria",
        "culinaria": "culinaria", "natureza": "natureza",
    }
    _DIF_MAP = {
        "fácil": "facil", "facil": "facil",
        "médio": "medio", "medio": "medio",
        "difícil": "dificil", "dificil": "dificil",
        "gigante": "gigante",
    }

    def _do_fix():
        import re
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute(
                "SELECT p.id, p.nome FROM produtos p "
                "JOIN topicos t ON p.topico_id = t.id "
                "WHERE t.slug = 'caca-palavras' AND (p.tema IS NULL OR p.dificuldade IS NULL)"
            )
            rows = [database._row_to_dict(r, cur) if database.USE_POSTGRES else dict(r) for r in cur.fetchall()]
            updated = []
            for row in rows:
                nome_lower = row["nome"].lower()
                tema = "geral"
                for k, v in _TEMA_MAP.items():
                    if k in nome_lower:
                        tema = v
                        break
                dif = None
                for k, v in _DIF_MAP.items():
                    if k in nome_lower:
                        dif = v
                        break
                if dif:
                    cur.execute(
                        f"UPDATE produtos SET tema = {database.PH}, dificuldade = {database.PH} WHERE id = {database.PH}",
                        (tema, dif, row["id"])
                    )
                    updated.append({"id": row["id"], "nome": row["nome"], "tema": tema, "dificuldade": dif})
            conn.commit()
            return updated

    result = await asyncio.to_thread(_do_fix)
    return {"corrigidos": len(result), "detalhes": result}


@app.post("/api/admin/fix-precos-kits")
async def fix_precos_kits(_auth=Depends(_require_auth)):
    """Recalcula e corrige o preço de todos os anúncios de kit ainda não publicados."""
    alteracoes = await asyncio.to_thread(database.fix_precos_kits_db)
    return {"corrigidos": len(alteracoes), "detalhes": alteracoes}


@app.post("/api/admin/fix-precos-kits-ml")
async def fix_precos_kits_ml(background_tasks: BackgroundTasks, _auth=Depends(_require_auth)):
    """Recalcula preços de TODOS os kits (incluindo publicados) e atualiza no ML.
    Roda em background — retorna imediatamente."""

    async def _run():
        import json as _json
        import time as _time

        # 1. Busca todos os anúncios de kit (qualquer status exceto deletado)
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute("""
                SELECT an.id, an.kit_id, an.preco, an.ml_id, an.status, k.apostila_ids
                FROM anuncios an
                JOIN kits k ON an.kit_id = k.id
                WHERE an.kit_id IS NOT NULL AND (an.status IS NULL OR an.status != 'deletado')
            """)
            rows = database._rows_to_dicts(cur.fetchall(), cur)

        # 2. Calcula preço correto por kit (cache para não repetir o cálculo)
        kits_preco: dict = {}
        for row in rows:
            kit_id = row["kit_id"]
            if kit_id not in kits_preco:
                try:
                    apostila_ids = _json.loads(row.get("apostila_ids") or "[]")
                except Exception:
                    apostila_ids = []
                total = 0.0
                for aid in apostila_ids:
                    ap = await asyncio.to_thread(database.buscar_apostila_por_id, aid)
                    num_ex = (ap or {}).get("num_exercicios", 60)
                    # Busca preço real do anúncio individual
                    ans = await asyncio.to_thread(
                        database.listar_anuncios, None, None, None, None, aid, 10
                    )
                    preco_ap = next(
                        (float(a["preco"]) for a in ans if float(a.get("preco") or 0) > 50 and not a.get("kit_id")),
                        _PRECOS_PRODUTO.get(num_ex, 79.99)
                    )
                    total += preco_ap
                kits_preco[kit_id] = pricing.preco_kit(total)

        # 3. Atualiza DB e ML para cada anúncio com preço diferente
        corrigidos_db = 0
        corrigidos_ml = 0
        erros = []
        for row in rows:
            novo_preco = kits_preco.get(row["kit_id"])
            if novo_preco is None:
                continue
            preco_atual = float(row.get("preco") or 0)
            if abs(preco_atual - novo_preco) < 0.01:
                continue

            # Atualiza DB
            await asyncio.to_thread(database.atualizar_anuncio, row["id"], preco=novo_preco)
            corrigidos_db += 1

            # Atualiza ML se publicado
            if row.get("ml_id") and row.get("status") == "publicado":
                try:
                    await asyncio.to_thread(ml_client.atualizar_preco_ml, row["ml_id"], novo_preco)
                    corrigidos_ml += 1
                except Exception as e:
                    erros.append({"anuncio_id": row["id"], "ml_id": row["ml_id"], "erro": str(e)})
                await asyncio.sleep(0.3)

        print(f"[fix-precos-kits-ml] DB={corrigidos_db} ML={corrigidos_ml} erros={len(erros)}")

    background_tasks.add_task(_run)
    return {"ok": True, "msg": "Correção de preços iniciada em background (DB + ML)"}


@app.post("/api/admin/gerar-caca-palavras")
async def admin_gerar_caca_palavras(_auth=Depends(_require_auth)):
    """Cria caça-palavras para todos os temas ainda não existentes."""
    import scheduler as sched
    await asyncio.to_thread(sched.gerar_caca_palavras_automaticos)
    return {"ok": True}


@app.post("/api/admin/gerar-kits-caca-palavras")
async def admin_gerar_kits_caca_palavras(background_tasks: BackgroundTasks, _auth=Depends(_require_auth)):
    """Cria kits combinando temas de caça-palavras (roda em background — retorna imediatamente)."""
    import scheduler as sched
    background_tasks.add_task(asyncio.to_thread, sched.gerar_kits_caca_palavras_automaticos)
    return {"ok": True, "msg": "Criação de kits CP iniciada em background"}


@app.get("/api/admin/debug-cp-mapa")
async def debug_cp_mapa(_auth=Depends(_require_auth)):
    """Retorna o mapa {dificuldade: {tema: apostila_id}} usado para criar kits CP."""
    mapa = await asyncio.to_thread(database.listar_apostilas_caca_palavras_por_dificuldade)
    summary = {dif: list(temas.keys()) for dif, temas in mapa.items()}
    return {"mapa_summary": summary, "mapa_full": mapa}


@app.post("/api/admin/ml/fix-caracteristicas")
async def fix_caracteristicas_ml(_auth=Depends(_require_auth), limite: int = 80, offset: int = 0):
    """Atualiza FORMAT, VERSION e WITH_UNLIMITED_LICENSE em todos os anúncios publicados no ML."""
    from ml import auth as ml_auth
    import requests as _req

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    anuncios = await asyncio.to_thread(database.listar_anuncios, "publicado", None, None, None, None, limite, offset)
    anuncios_ml = [a for a in anuncios if a.get("ml_id")]

    atualizados, erros = [], []
    for an in anuncios_ml:
        is_digital = an.get("tipo") == "digital"
        attrs = [
            {"id": "FORMAT", "value_id": "2132699" if is_digital else "2431740",
             "value_name": "Digital" if is_digital else "Físico"},
            {"id": "VERSION",               "value_name": "1ª Edição"},
            {"id": "WITH_UNLIMITED_LICENSE","value_id": "242084", "value_name": "Não"},
        ]

        async def _put(ml_id=an["ml_id"]):
            for attempt in range(3):
                r = await asyncio.to_thread(
                    lambda: _req.put(
                        f"https://api.mercadolibre.com/items/{ml_id}",
                        json={"attributes": attrs},
                        headers=headers,
                        timeout=15,
                    )
                )
                if r.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return r
            return r

        r = await _put()
        await asyncio.sleep(0.3)  # 3 req/s para não bater no rate limit
        if r.status_code == 200:
            atualizados.append(an["ml_id"])
        elif "not_modifiable" in r.text:
            pass  # atributo bloqueado pelo ML — não há o que fazer via API
        else:
            erros.append({"ml_id": an["ml_id"], "status": r.status_code, "detail": r.text[:200]})

    return {"atualizados": len(atualizados), "erros": len(erros), "proximo_offset": offset + limite, "detalhes_erros": erros}


@app.post("/api/admin/ml/fix-categorias")
async def fix_categorias_ml(_auth=Depends(_require_auth)):
    """Atualiza a categoria de todos os anúncios publicados no ML para a categoria correta
    (físico → MLB437616 Livros Físicos, digital → MLB1227 Outros/Livros)."""
    try:
        resultado = await asyncio.to_thread(ml_client.fix_categorias_ml)
        return resultado
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
async def ml_callback(code: str, state: str = ""):
    try:
        from ml import auth as ml_auth_module
        from datetime import datetime, timedelta
        from fastapi.responses import RedirectResponse
        if not ml_auth_module.consume_state(state):
            raise HTTPException(status_code=400, detail="state inválido ou expirado — reinicie a conexão pelo dashboard")
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


@app.get("/api/admin/ml-diagnostico")
async def ml_diagnostico(_=Depends(_require_auth)):
    """Busca anúncios inativos/pausados no ML e agrupa por motivo."""
    from ml import auth as ml_auth
    import requests as _req

    token = await asyncio.to_thread(ml_auth.get_valid_token)
    headers = {"Authorization": f"Bearer {token}"}

    me_r = await asyncio.to_thread(
        lambda: _req.get("https://api.mercadolibre.com/users/me", headers=headers, timeout=15)
    )
    user_id = me_r.json()["id"]

    async def _buscar_ids(status: str) -> list:
        ids = []
        offset = 0
        while True:
            resp = await asyncio.to_thread(
                lambda o=offset: _req.get(
                    f"https://api.mercadolibre.com/users/{user_id}/items/search",
                    params={"status": status, "limit": 100, "offset": o},
                    headers=headers, timeout=15,
                )
            )
            data = resp.json()
            batch = data.get("results", [])
            ids.extend(batch)
            total = data.get("paging", {}).get("total", 0)
            offset += len(batch)
            if offset >= total or not batch:
                break
        return ids

    async def _batch_detalhes(ids: list) -> list:
        detalhes = []
        for i in range(0, min(len(ids), 200), 20):
            chunk = ids[i:i + 20]
            resp = await asyncio.to_thread(
                lambda c=chunk: _req.get(
                    "https://api.mercadolibre.com/items",
                    params={"ids": ",".join(c), "attributes": "id,status,sub_status,title,warnings,health"},
                    headers=headers, timeout=15,
                )
            )
            for entry in resp.json():
                if isinstance(entry, dict) and entry.get("code") == 200:
                    detalhes.append(entry["body"])
            await asyncio.sleep(0.2)
        return detalhes

    # Debug: confirma user_id e testa API
    debug_info = {"user_id": user_id}

    resultado = {}
    for status in ["active", "paused", "under_review", "inactive", "closed"]:
        ids = await _buscar_ids(status)
        if not ids:
            continue
        detalhes = await _batch_detalhes(ids)

        por_motivo: dict = {}
        for item in detalhes:
            sub = tuple(sorted(item.get("sub_status") or []))
            warnings = [w.get("code", w) for w in (item.get("warnings") or [])]
            chave = str(sub or warnings or "sem_motivo")
            por_motivo.setdefault(chave, []).append({
                "id": item.get("id"),
                "titulo": (item.get("title") or "")[:60],
                "health": item.get("health"),
            })

        resultado[status] = {
            "total_ids": len(ids),
            "amostrados": len(detalhes),
            "por_motivo": {
                k: {"quantidade": len(v), "exemplos": v[:3]}
                for k, v in sorted(por_motivo.items(), key=lambda x: -len(x[1]))
            },
        }

    return {"debug": debug_info, "resultado": resultado}


@app.get("/api/admin/ml-problemas")
async def ml_problemas(_=Depends(_require_auth)):
    """Busca todos os anúncios do banco com ml_id e verifica status/sub_status direto na ML API."""
    from ml import auth as ml_auth
    import requests as _req
    from database import _get_conn, _cursor, _rows_to_dicts

    token = await asyncio.to_thread(ml_auth.get_valid_token)
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_ml_ids():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT id, ml_id, titulo FROM anuncios WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'")
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = await asyncio.to_thread(_buscar_ml_ids)
    ml_ids = [a["ml_id"] for a in anuncios]
    id_map = {a["ml_id"]: a for a in anuncios}

    problemas = []
    ok = 0

    for i in range(0, len(ml_ids), 20):
        chunk = ml_ids[i:i + 20]
        resp = await asyncio.to_thread(
            lambda c=chunk: _req.get(
                "https://api.mercadolibre.com/items",
                params={"ids": ",".join(c), "attributes": "id,status,sub_status,title,warnings"},
                headers=headers, timeout=15,
            )
        )
        for entry in resp.json():
            if not isinstance(entry, dict) or entry.get("code") != 200:
                continue
            item = entry["body"]
            ml_status = item.get("status", "")
            sub_status = item.get("sub_status") or []
            warnings = [w.get("code") or str(w) for w in (item.get("warnings") or [])]

            if ml_status == "active" and not sub_status and not warnings:
                ok += 1
                continue

            problemas.append({
                "ml_id": item.get("id"),
                "titulo": (item.get("title") or "")[:60],
                "status": ml_status,
                "sub_status": sub_status,
                "warnings": warnings,
                "anuncio_id": id_map.get(item.get("id"), {}).get("id"),
            })
        await asyncio.sleep(0.3)

    por_motivo: dict = {}
    for p in problemas:
        chave = str(p["sub_status"] or p["warnings"] or p["status"])
        por_motivo.setdefault(chave, []).append(p)

    return {
        "total_verificados": len(ml_ids),
        "ok": ok,
        "com_problema": len(problemas),
        "por_motivo": {
            k: {"quantidade": len(v), "exemplos": v[:2]}
            for k, v in sorted(por_motivo.items(), key=lambda x: -len(x[1]))
        },
    }


@app.get("/api/admin/ml-forbidden-detalhe")
async def ml_forbidden_detalhe(_=Depends(_require_auth)):
    """Busca detalhes completos dos itens com sub_status forbidden para entender o motivo real."""
    from ml import auth as ml_auth
    import requests as _req
    from database import _get_conn, _cursor, _rows_to_dicts

    token = await asyncio.to_thread(ml_auth.get_valid_token)
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_forbidden_ids():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT id, ml_id, titulo, tipo FROM anuncios WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'")
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = await asyncio.to_thread(_buscar_forbidden_ids)
    ml_ids = [a["ml_id"] for a in anuncios]
    id_map = {a["ml_id"]: a for a in anuncios}

    # Primeiro passo: encontra todos os forbidden
    forbidden_ids = []
    for i in range(0, len(ml_ids), 20):
        chunk = ml_ids[i:i + 20]
        resp = await asyncio.to_thread(
            lambda c=chunk: _req.get(
                "https://api.mercadolibre.com/items",
                params={"ids": ",".join(c), "attributes": "id,status,sub_status"},
                headers=headers, timeout=15,
            )
        )
        for entry in resp.json():
            if not isinstance(entry, dict) or entry.get("code") != 200:
                continue
            item = entry["body"]
            subs = item.get("sub_status") or []
            if "forbidden" in subs:
                forbidden_ids.append(item["id"])
        await asyncio.sleep(0.2)

    # Segundo passo: busca detalhes completos de cada forbidden (tags, health, cause)
    detalhes = []
    for ml_id in forbidden_ids[:150]:  # limita 150
        resp = await asyncio.to_thread(
            lambda mid=ml_id: _req.get(
                f"https://api.mercadolibre.com/items/{mid}",
                params={"attributes": "id,status,sub_status,title,tags,health,cause,category_id,listing_type_id"},
                headers=headers, timeout=15,
            )
        )
        item = resp.json()
        an = id_map.get(ml_id, {})
        detalhes.append({
            "ml_id": ml_id,
            "anuncio_id": an.get("id"),
            "titulo_db": (an.get("titulo") or "")[:60],
            "tipo_db": an.get("tipo"),
            "titulo_ml": (item.get("title") or "")[:60],
            "status": item.get("status"),
            "sub_status": item.get("sub_status") or [],
            "tags": item.get("tags") or [],
            "health": item.get("health"),
            "cause": item.get("cause"),
            "category_id": item.get("category_id"),
        })
        await asyncio.sleep(0.15)

    # Agrupa por tags (principal indicador do problema real)
    por_tags: dict = {}
    for d in detalhes:
        chave = str(sorted(d["tags"])) if d["tags"] else "sem_tags"
        por_tags.setdefault(chave, []).append(d)

    return {
        "total_forbidden": len(forbidden_ids),
        "analisados": len(detalhes),
        "por_tags": {
            k: {"quantidade": len(v), "exemplos": v[:3]}
            for k, v in sorted(por_tags.items(), key=lambda x: -len(x[1]))
        },
        "lista_completa": detalhes,
    }


@app.post("/api/admin/fix-forbidden-deletados")
async def fix_forbidden_deletados(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Para itens com forbidden+suspended_for_prevention+deleted no ML:
    - tipo=importado → marca como deletado no banco (listagens antigas sem substituto)
    - tipo=digital   → limpa ml_id + re-publica em categoria correta (MLB1227)
    - tipo=fisico    → marca como deletado no banco
    """
    background_tasks.add_task(_fix_forbidden_deletados_bg)
    return {"ok": True, "msg": "Fix forbidden+deletados iniciado em background"}


async def _fix_forbidden_deletados_bg():
    from ml import auth as ml_auth
    import requests as _req
    import ml.client as ml_client
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    token = await asyncio.to_thread(ml_auth.get_valid_token)
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_todos():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT id, ml_id, titulo, tipo FROM anuncios WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'")
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = await asyncio.to_thread(_buscar_todos)
    ml_ids = [a["ml_id"] for a in anuncios]
    id_map = {a["ml_id"]: a for a in anuncios}

    # Coleta todos os ml_ids com forbidden+suspended+deleted
    forbidden_deletados = []
    for i in range(0, len(ml_ids), 20):
        chunk = ml_ids[i:i + 20]
        resp = await asyncio.to_thread(
            lambda c=chunk: _req.get(
                "https://api.mercadolibre.com/items",
                params={"ids": ",".join(c), "attributes": "id,status,sub_status"},
                headers=headers, timeout=15,
            )
        )
        for entry in resp.json():
            if not isinstance(entry, dict) or entry.get("code") != 200:
                continue
            item = entry["body"]
            subs = set(item.get("sub_status") or [])
            if "forbidden" in subs and "deleted" in subs:
                forbidden_deletados.append(id_map[item["id"]])
        await asyncio.sleep(0.2)

    print(f"[fix-forbidden] encontrados {len(forbidden_deletados)} forbidden+deleted")

    def _marcar_deletado(anuncio_id):
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"UPDATE anuncios SET status = 'deletado', ml_id = NULL WHERE id = {PH}", [anuncio_id])
            conn.commit()

    def _limpar_para_republicar(anuncio_id):
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"UPDATE anuncios SET ml_id = NULL, status = 'rascunho', erro_msg = NULL WHERE id = {PH}", [anuncio_id])
            conn.commit()

    deletados = []
    republicados = []
    erros = []

    for an in forbidden_deletados:
        tipo = an.get("tipo") or ""
        anuncio_id = an["id"]

        if tipo in ("importado", "fisico"):
            await asyncio.to_thread(_marcar_deletado, anuncio_id)
            deletados.append(anuncio_id)
        elif tipo == "digital":
            await asyncio.to_thread(_limpar_para_republicar, anuncio_id)
            try:
                novo_ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, anuncio_id)
                republicados.append({"anuncio_id": anuncio_id, "novo_ml_id": novo_ml_id})
            except Exception as e:
                erros.append({"anuncio_id": anuncio_id, "erro": str(e)[:200]})
            await asyncio.sleep(0.5)

    print(f"[fix-forbidden] deletados={len(deletados)} republicados={len(republicados)} erros={len(erros)}")


@app.post("/api/admin/reverter-para-fisico")
async def reverter_para_fisico(_=Depends(_require_auth)):
    """
    Reverte toda a base para produto físico:
    - tipo='fisico' em todos os anúncios
    - Remove 'PDF' e 'Digital' dos títulos
    - Arquiva caça-palavras (status='arquivado', ml_id=NULL) — não re-publica no ML
    """
    import re
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    def _run():
        with _get_conn() as conn:
            cur = _cursor(conn)

            # 1. Todos para fisico
            cur.execute("UPDATE anuncios SET tipo = 'fisico' WHERE tipo != 'fisico' AND status != 'deletado'")
            fisico_count = cur.rowcount

            # 2. Remove PDF/Digital dos títulos
            cur.execute("SELECT id, titulo FROM anuncios WHERE status != 'deletado' AND status != 'arquivado'")
            rows = _rows_to_dicts(cur.fetchall(), cur)
            titulo_count = 0
            for row in rows:
                titulo = row["titulo"] or ""
                novo = re.sub(r'\s*PDF\s*Digital\b', '', titulo, flags=re.IGNORECASE)
                novo = re.sub(r'\bPDF\b', '', novo, flags=re.IGNORECASE)
                novo = re.sub(r'\bDigital\b', '', novo, flags=re.IGNORECASE)
                novo = re.sub(r'\s+', ' ', novo).strip().strip('-').strip()
                novo = novo[:60]
                if novo != titulo:
                    cur.execute(f"UPDATE anuncios SET titulo = {PH} WHERE id = {PH}", [novo, row["id"]])
                    titulo_count += 1

            # 3. Arquiva caça-palavras — identifica por kit/apostila/título
            cur.execute("""
                UPDATE anuncios SET status = 'arquivado', ml_id = NULL
                WHERE status NOT IN ('deletado', 'arquivado')
                  AND (
                    titulo ILIKE '%palavras%'
                    OR kit_id IN (SELECT id FROM kits WHERE nome ILIKE '%palavras%')
                  )
            """)
            cp_count = cur.rowcount

            conn.commit()
            return {"fisico_revertidos": fisico_count, "titulos_corrigidos": titulo_count, "cp_arquivados": cp_count}

    resultado = await asyncio.to_thread(_run)
    return {"ok": True, **resultado}


@app.post("/api/admin/sincronizar-titulos-ml")
async def sincronizar_titulos_ml(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Atualiza no ML os títulos corrigidos (sem PDF/Digital) para todos os anúncios
    com ml_id ativo no banco. Roda em background, ~1 req/s.
    """
    background_tasks.add_task(_sincronizar_titulos_ml_bg)
    return {"ok": True, "msg": "Sincronização de títulos iniciada em background — verifique os logs"}


@app.post("/api/admin/corrigir-titulos-ml")
async def corrigir_titulos_ml(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Corrige títulos no ML via pausa → atualiza título → reativa.
    Necessário porque o ML não permite editar título de anúncios ativos.
    Só reativa os que estavam ativos antes — pausados permanecem pausados.
    """
    background_tasks.add_task(_corrigir_titulos_ml_bg)
    return {"ok": True, "msg": "Correção de títulos iniciada em background — verifique os logs"}


async def _corrigir_titulos_ml_bg():
    import re
    import requests as _req
    from ml import auth as ml_auth, client as ml_client
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[corrigir-titulos] Token ML inválido: {e}")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _buscar_ativos():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                "SELECT id, ml_id, titulo FROM anuncios "
                "WHERE ml_id IS NOT NULL AND ml_id != '' "
                "AND status NOT IN ('deletado', 'arquivado')"
            )
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = await asyncio.to_thread(_buscar_ativos)
    print(f"[corrigir-titulos] {len(anuncios)} anúncios candidatos")

    atualizados = 0
    pulados = 0
    erros = 0

    for an in anuncios:
        ml_id = an["ml_id"]
        titulo_novo = (an["titulo"] or "")[:60]

        # 1. Busca status atual no ML
        r = await asyncio.to_thread(
            lambda mid=ml_id: _req.get(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                params={"attributes": "id,title,status"},
                headers=headers, timeout=10,
            )
        )
        await asyncio.sleep(0.5)

        if r.status_code != 200:
            erros += 1
            print(f"[corrigir-titulos] ERRO ao buscar {ml_id}: {r.status_code}")
            continue

        item = r.json()
        titulo_ml = item.get("title", "")
        status_ml = item.get("status", "")

        # Pula se o título já está correto
        if "pdf" not in titulo_ml.lower() and "digital" not in titulo_ml.lower():
            pulados += 1
            continue

        era_ativo = status_ml == "active"

        # 2. Pausa se estiver ativo
        if era_ativo:
            r2 = await asyncio.to_thread(
                lambda mid=ml_id: _req.put(
                    f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                    json={"status": "paused"},
                    headers=headers, timeout=10,
                )
            )
            await asyncio.sleep(2)
            if r2.status_code != 200:
                erros += 1
                print(f"[corrigir-titulos] ERRO ao pausar {ml_id}: {r2.status_code} {r2.text[:150]}")
                continue

        # 3. Atualiza título
        r3 = await asyncio.to_thread(
            lambda mid=ml_id, t=titulo_novo: _req.put(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                json={"title": t},
                headers=headers, timeout=10,
            )
        )
        await asyncio.sleep(1)

        if r3.status_code != 200:
            erros += 1
            print(f"[corrigir-titulos] ERRO ao atualizar título {ml_id}: {r3.status_code} {r3.text[:150]}")
            # Tenta reativar mesmo assim se era ativo
            if era_ativo:
                await asyncio.to_thread(
                    lambda mid=ml_id: _req.put(
                        f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                        json={"status": "active"},
                        headers=headers, timeout=10,
                    )
                )
                await asyncio.sleep(1)
            continue

        # 4. Reativa se era ativo
        if era_ativo:
            r4 = await asyncio.to_thread(
                lambda mid=ml_id: _req.put(
                    f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                    json={"status": "active"},
                    headers=headers, timeout=10,
                )
            )
            await asyncio.sleep(1)
            if r4.status_code != 200:
                print(f"[corrigir-titulos] AVISO: título atualizado mas falhou ao reativar {ml_id}: {r4.status_code}")

        atualizados += 1
        print(f"[corrigir-titulos] OK {ml_id}: '{titulo_ml[:40]}' → '{titulo_novo[:40]}'")

    print(f"[corrigir-titulos] concluído — atualizados={atualizados} pulados={pulados} erros={erros}")


async def _sincronizar_titulos_ml_bg():
    import time as _time
    from ml import auth as ml_auth, client as ml_client
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[sinc-titulos] Token ML inválido: {e}")
        return

    def _buscar_ativos():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                "SELECT id, ml_id, titulo FROM anuncios "
                "WHERE ml_id IS NOT NULL AND ml_id != '' "
                "AND status NOT IN ('deletado', 'arquivado')"
            )
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = await asyncio.to_thread(_buscar_ativos)
    print(f"[sinc-titulos] {len(anuncios)} anúncios para sincronizar")

    import requests as _req
    atualizados = 0
    erros = 0
    for an in anuncios:
        ml_id = an["ml_id"]
        titulo = (an["titulo"] or "")[:60]
        resp = await asyncio.to_thread(
            lambda mid=ml_id, t=titulo: _req.put(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                json={"title": t},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=10,
            )
        )
        if resp.status_code == 200:
            atualizados += 1
        else:
            erros += 1
            print(f"[sinc-titulos] ERRO {ml_id}: {resp.status_code} {resp.text[:200]}")
        await asyncio.sleep(1)

    print(f"[sinc-titulos] concluído — atualizados={atualizados} erros={erros}")


@app.post("/api/admin/pausar-cp-ml")
async def pausar_cp_ml(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Busca todos os anúncios ativos no ML com 'palavras' no título e os fecha.
    Necessário porque o reverter-para-fisico zerou os ml_ids localmente.
    """
    background_tasks.add_task(_pausar_cp_ml_bg)
    return {"ok": True, "msg": "Pausar caça-palavras ML iniciado em background — verifique os logs"}


async def _pausar_cp_ml_bg():
    import time as _time
    import requests as _req
    from ml import auth as ml_auth, client as ml_client

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[pausar-cp] Token ML inválido: {e}")
        return

    headers = {"Authorization": f"Bearer {token}"}

    # Busca user_id
    me = await asyncio.to_thread(lambda: _req.get(f"{ml_client.ML_API_BASE}/users/me", headers=headers, timeout=10))
    if me.status_code != 200:
        print(f"[pausar-cp] Erro ao buscar usuário: {me.text}")
        return
    user_id = me.json()["id"]

    # Lista todos os item IDs ativos
    item_ids = []
    offset = 0
    while True:
        r = await asyncio.to_thread(
            lambda o=offset: _req.get(
                f"{ml_client.ML_API_BASE}/users/{user_id}/items/search",
                params={"offset": o, "limit": 50},
                headers=headers, timeout=10,
            )
        )
        if r.status_code != 200:
            break
        results = r.json().get("results", [])
        item_ids.extend(results)
        if len(results) < 50:
            break
        offset += 50

    print(f"[pausar-cp] {len(item_ids)} itens ativos no ML")

    # Busca detalhes em lote de 20 e filtra caça-palavras
    cp_ids = []
    for i in range(0, len(item_ids), 20):
        batch = item_ids[i:i+20]
        r = await asyncio.to_thread(
            lambda b=batch: _req.get(
                f"{ml_client.ML_API_BASE}/items",
                params={"ids": ",".join(b)},
                headers=headers, timeout=10,
            )
        )
        if r.status_code != 200:
            continue
        for entry in r.json():
            item = entry.get("body", {})
            titulo = item.get("title", "")
            if "palavras" in titulo.lower():
                cp_ids.append(item.get("id", ""))

    print(f"[pausar-cp] {len(cp_ids)} caça-palavras encontrados no ML")

    fechados = 0
    erros = 0
    for ml_id in cp_ids:
        if not ml_id:
            continue
        resp = await asyncio.to_thread(
            lambda mid=ml_id: _req.put(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                json={"status": "closed"},
                headers={**headers, "Content-Type": "application/json"},
                timeout=10,
            )
        )
        if resp.status_code == 200:
            fechados += 1
        else:
            erros += 1
            print(f"[pausar-cp] ERRO {ml_id}: {resp.status_code} {resp.text[:200]}")
        await asyncio.sleep(1)

    print(f"[pausar-cp] concluído — fechados={fechados} erros={erros}")


@app.post("/api/admin/reativar-waiting-patch")
async def reativar_waiting_patch(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Fecha anúncios under_review/waiting_for_patch no ML e re-publica como FÍSICO.
    Busca ml_ids em lotes de 20 para eficiência, depois fecha e republica um por um.
    """
    background_tasks.add_task(_reativar_waiting_patch_bg)
    return {"ok": True, "msg": "Reativação waiting_for_patch iniciada em background — verifique os logs"}


async def _reativar_waiting_patch_bg():
    import requests as _req
    from ml import auth as ml_auth, client as ml_client
    import ml.client as _ml
    from database import _get_conn, _cursor, PH, _rows_to_dicts, atualizar_anuncio

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[reativar-wp] Token ML inválido: {e}")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Busca todos os anúncios com ml_id do banco
    def _buscar_com_ml_id():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                "SELECT id, ml_id, titulo FROM anuncios "
                "WHERE ml_id IS NOT NULL AND ml_id != '' "
                "AND status NOT IN ('deletado', 'arquivado')"
            )
            return _rows_to_dicts(cur.fetchall(), cur)

    todos = await asyncio.to_thread(_buscar_com_ml_id)
    ml_id_map = {a["ml_id"]: a for a in todos}
    ml_ids = list(ml_id_map.keys())
    print(f"[reativar-wp] {len(ml_ids)} anúncios com ml_id para verificar")

    # 2. Busca status em lotes de 20
    waiting_patch = []
    for i in range(0, len(ml_ids), 20):
        batch = ml_ids[i:i+20]
        r = await asyncio.to_thread(
            lambda b=batch: _req.get(
                f"{ml_client.ML_API_BASE}/items",
                params={"ids": ",".join(b), "attributes": "id,status,sub_status"},
                headers=headers, timeout=15,
            )
        )
        await asyncio.sleep(0.5)
        if r.status_code != 200:
            print(f"[reativar-wp] ERRO no lote {i}: {r.status_code}")
            continue
        for entry in r.json():
            item = entry.get("body", {})
            sub = item.get("sub_status", [])
            if "waiting_for_patch" in sub:
                ml_id = item.get("id", "")
                if ml_id and ml_id in ml_id_map:
                    waiting_patch.append(ml_id_map[ml_id])

    print(f"[reativar-wp] {len(waiting_patch)} anúncios waiting_for_patch encontrados")

    # 3. Para cada: fecha no ML → limpa ml_id local → re-publica como físico
    ok = 0
    erros = 0
    for an in waiting_patch:
        anuncio_id = an["id"]
        ml_id_antigo = an["ml_id"]

        # Fecha listing antigo
        r_close = await asyncio.to_thread(
            lambda mid=ml_id_antigo: _req.put(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                json={"status": "closed"},
                headers=headers, timeout=10,
            )
        )
        await asyncio.sleep(2)
        if r_close.status_code not in (200, 400):  # 400 = já fechado, ok
            erros += 1
            print(f"[reativar-wp] ERRO ao fechar {ml_id_antigo}: {r_close.status_code} {r_close.text[:150]}")
            continue

        # Limpa ml_id local para permitir re-publicação
        await asyncio.to_thread(lambda aid=anuncio_id: atualizar_anuncio(aid, ml_id="", status="rascunho"))

        # Re-publica como físico
        try:
            novo_ml_id = await asyncio.to_thread(lambda aid=anuncio_id: _ml.publicar_anuncio(aid))
            ok += 1
            print(f"[reativar-wp] OK {ml_id_antigo} → {novo_ml_id} ({an['titulo'][:40]})")
        except Exception as e:
            erros += 1
            print(f"[reativar-wp] ERRO ao republicar anuncio_id={anuncio_id}: {e}")

        await asyncio.sleep(3)

    print(f"[reativar-wp] concluído — ok={ok} erros={erros}")


@app.post("/api/admin/fix-waiting-for-patch")
async def fix_waiting_for_patch(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Fecha anúncios under_review/waiting_for_patch no ML e re-publica como digital.
    Necessário porque anúncios criados como físico não podem ser convertidos via PUT simples.
    """
    background_tasks.add_task(_fix_waiting_for_patch_bg)
    return {"ok": True, "msg": "Fix waiting_for_patch iniciado em background"}


async def _fix_waiting_for_patch_bg():
    from ml import auth as ml_auth
    import requests as _req
    import ml.client as ml_client
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    token = await asyncio.to_thread(ml_auth.get_valid_token)
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_todos():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT id, ml_id, titulo, tipo FROM anuncios WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'")
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = await asyncio.to_thread(_buscar_todos)
    ml_ids = [a["ml_id"] for a in anuncios]
    id_map = {a["ml_id"]: a for a in anuncios}

    # Encontra todos os waiting_for_patch
    waiting = []
    for i in range(0, len(ml_ids), 20):
        chunk = ml_ids[i:i + 20]
        resp = await asyncio.to_thread(
            lambda c=chunk: _req.get(
                "https://api.mercadolibre.com/items",
                params={"ids": ",".join(c), "attributes": "id,status,sub_status"},
                headers=headers, timeout=15,
            )
        )
        for entry in resp.json():
            if not isinstance(entry, dict) or entry.get("code") != 200:
                continue
            item = entry["body"]
            subs = item.get("sub_status") or []
            if "waiting_for_patch" in subs and item.get("status") == "under_review":
                waiting.append(id_map[item["id"]])
        await asyncio.sleep(0.2)

    print(f"[fix-wfp] encontrados {len(waiting)} waiting_for_patch para fechar e re-publicar")

    def _fechar_e_limpar(anuncio_id, ml_id):
        # Fecha no ML
        _req.put(
            f"https://api.mercadolibre.com/items/{ml_id}",
            json={"status": "closed"},
            headers=headers,
            timeout=15,
        )
        # Limpa no banco
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"UPDATE anuncios SET ml_id = NULL, status = 'rascunho', erro_msg = NULL WHERE id = {PH}", [anuncio_id])
            conn.commit()

    fechados = 0
    republicados = []
    erros = []

    for an in waiting:
        try:
            await asyncio.to_thread(_fechar_e_limpar, an["id"], an["ml_id"])
            fechados += 1
            await asyncio.sleep(0.3)
            novo_ml_id = await asyncio.to_thread(ml_client.publicar_anuncio, an["id"])
            republicados.append({"anuncio_id": an["id"], "novo_ml_id": novo_ml_id})
        except Exception as e:
            erros.append({"anuncio_id": an["id"], "erro": str(e)[:200]})
            print(f"[fix-wfp] erro anuncio_id={an['id']}: {e}")
        await asyncio.sleep(0.5)

    print(f"[fix-wfp] fechados={fechados} republicados={len(republicados)} erros={len(erros)}")


async def _fix_caca_palavras_digital_bg():
    from ml import auth as ml_auth
    import requests as _req
    from database import _get_conn, _cursor, PH, _rows_to_dicts
    import re

    token = ml_auth.get_valid_token()
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_cp():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"""
                SELECT a.id, a.ml_id, a.titulo, a.tipo
                FROM anuncios a
                LEFT JOIN kits k ON a.kit_id = k.id
                LEFT JOIN apostilas ap ON a.apostila_id = ap.id
                LEFT JOIN produtos pr ON ap.produto_id = pr.id
                WHERE a.ml_id IS NOT NULL AND a.ml_id != ''
                  AND a.status != 'deletado'
                  AND a.tipo = 'fisico'
                  AND (
                    k.nome ILIKE '%palavras%'
                    OR a.titulo ILIKE '%palavras%'
                    OR pr.nome ILIKE '%palavras%'
                  )
            """)
            return _rows_to_dicts(cur.fetchall(), cur)

    def _fix_titulo(titulo: str) -> str:
        remover = ["Impresso", "Impressa", "Impressos", "Físico", "Física",
                   "Fisico", "Fisica", "Físicos", "Físicas", "Atividade Físico"]
        t = titulo
        for palavra in remover:
            t = re.sub(rf'\b{re.escape(palavra)}\b', '', t, flags=re.IGNORECASE)
        t = re.sub(r'\s+', ' ', t).strip().strip('-').strip()
        # Garante PDF no título
        if "pdf" not in t.lower():
            sufixo = " PDF"
            max_base = 60 - len(sufixo)
            if len(t) > max_base:
                t = t[:max_base].rsplit(" ", 1)[0]
            t = (t + sufixo)[:60]
        return t[:60]

    anuncios = await asyncio.to_thread(_buscar_cp)
    corrigidos = []
    erros = []

    def _atualizar_db(anuncio_id, novo_tipo, novo_titulo):
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                f"UPDATE anuncios SET tipo = {PH}, titulo = {PH} WHERE id = {PH}",
                [novo_tipo, novo_titulo, anuncio_id],
            )
            conn.commit()

    def _put_ml(ml_id, novo_titulo, hdrs):
        return _req.put(
            f"https://api.mercadolibre.com/items/{ml_id}",
            json={"title": novo_titulo, "category_id": "MLB1227"},
            headers=hdrs,
            timeout=15,
        )

    for an in anuncios:
        novo_titulo = _fix_titulo(an["titulo"])
        await asyncio.to_thread(_atualizar_db, an["id"], "digital", novo_titulo)
        r = await asyncio.to_thread(_put_ml, an["ml_id"], novo_titulo, headers)
        if r.status_code in (200, 201):
            corrigidos.append({"anuncio_id": an["id"], "ml_id": an["ml_id"], "novo_titulo": novo_titulo})
        else:
            erros.append({"anuncio_id": an["id"], "ml_id": an["ml_id"], "erro": r.text[:200]})
        await asyncio.sleep(0.4)

    print(f"[fix-cp-digital] corrigidos={len(corrigidos)} erros={len(erros)} total={len(anuncios)}")


async def _fix_imagens_pillow_bg():
    """Detecta anúncios publicados com imagem local (apagada pelo Render) e regenera via AI → R2."""
    from database import _get_conn, _cursor, PH, _rows_to_dicts
    import storage as _storage

    def _buscar_sem_imagem_r2():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"""
                SELECT id, apostila_id, kit_id, titulo, variacao, topico_id, num_exercicios
                FROM anuncios
                WHERE ml_id IS NOT NULL AND ml_id != ''
                  AND status = 'publicado'
                  AND (
                    imagem_path IS NULL
                    OR imagem_path = ''
                    OR imagem_path LIKE '/opt/render%'
                    OR imagem_path LIKE 'C:%'
                  )
                LIMIT 50
            """)
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = _buscar_sem_imagem_r2()
    print(f"[fix-imagens] {len(anuncios)} anúncios com imagem local/ausente para regenerar")

    regenerados = 0
    for an in anuncios:
        try:
            from generator import images as gen_images
            apostila_id = an.get("apostila_id")
            kit_id = an.get("kit_id")
            variacao = an.get("variacao") or 1

            if apostila_id:
                topico = {"id": an.get("topico_id"), "nome": an.get("titulo", ""), "slug": "geral"}
                num_ex = an.get("num_exercicios") or 60
                paths = await asyncio.to_thread(gen_images.gerar_capas, apostila_id, topico, num_ex)
            elif kit_id:
                kit = database.buscar_kit(kit_id)
                if not kit:
                    continue
                apostilas = [database.buscar_apostila_por_id(aid) for aid in kit.get("apostila_ids_list", [])]
                apostilas = [a for a in apostilas if a]
                paths = await asyncio.to_thread(gen_images.gerar_capas_kit, kit_id, kit.get("nome", ""), apostilas, variacao)
            else:
                continue

            if paths:
                r2_url = await asyncio.to_thread(_storage.upload, paths[0])
                await asyncio.to_thread(database.atualizar_anuncio, an["id"], imagem_path=r2_url)
                regenerados += 1
        except Exception as e:
            print(f"[fix-imagens] erro anuncio_id={an['id']}: {e}")
        await asyncio.sleep(2)

    print(f"[fix-imagens] regenerados={regenerados}/{len(anuncios)}")


async def _fix_titulos_bg():
    from ml import auth as ml_auth
    import requests as _req
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    token = ml_auth.get_valid_token()
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_duplicados():
        with _get_conn() as conn:
            cur = _cursor(conn)
            # Busca títulos com mais de 1 anúncio ativo com ml_id
            cur.execute(f"""
                SELECT a.id, a.ml_id, a.titulo, a.variacao, a.kit_id, a.apostila_id,
                       ap.num_exercicios, kt.nome AS kit_nome
                FROM anuncios a
                LEFT JOIN apostilas ap ON a.apostila_id = ap.id
                LEFT JOIN kits kt ON a.kit_id = kt.id
                WHERE a.ml_id IS NOT NULL AND a.ml_id != ''
                  AND a.status != 'deletado'
                  AND a.titulo IN (
                      SELECT titulo FROM anuncios
                      WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'
                      GROUP BY titulo HAVING COUNT(*) > 1
                  )
                ORDER BY a.titulo, a.id
            """)
            return _rows_to_dicts(cur.fetchall(), cur)

    duplicados = await asyncio.to_thread(_buscar_duplicados)

    # Agrupa por título
    por_titulo: dict = {}
    for an in duplicados:
        por_titulo.setdefault(an["titulo"], []).append(an)

    corrigidos = []
    erros = []

    def _upd_titulo_db(anuncio_id, novo_titulo):
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"UPDATE anuncios SET titulo = {PH} WHERE id = {PH}", [novo_titulo, anuncio_id])
            conn.commit()

    def _put_titulo_ml(ml_id, novo_titulo, hdrs):
        return _req.put(
            f"https://api.mercadolibre.com/items/{ml_id}",
            json={"title": novo_titulo},
            headers=hdrs,
            timeout=15,
        )

    for titulo_orig, grupo in por_titulo.items():
        for idx, an in enumerate(grupo, start=1):
            num_ex = an.get("num_exercicios") or 0
            variacao = an.get("variacao") or idx

            base = titulo_orig
            for suf in [" Vol. 1", " Vol. 2", " Vol. 3", " - Vol. 1", " - Vol. 2", " - Vol. 3"]:
                base = base.replace(suf, "")
            base = base.strip()

            sufixo = f" Vol. {variacao}"
            max_base = 60 - len(sufixo)
            if len(base) > max_base:
                base = base[:max_base].rsplit(" ", 1)[0]
            novo_titulo = (base + sufixo)[:60]

            if novo_titulo == titulo_orig:
                continue

            await asyncio.to_thread(_upd_titulo_db, an["id"], novo_titulo)
            r = await asyncio.to_thread(_put_titulo_ml, an["ml_id"], novo_titulo, headers)
            if r.status_code in (200, 201):
                corrigidos.append({"anuncio_id": an["id"], "ml_id": an["ml_id"], "novo_titulo": novo_titulo})
            else:
                erros.append({"anuncio_id": an["id"], "ml_id": an["ml_id"], "erro": r.text[:200]})
            await asyncio.sleep(0.4)

    print(f"[fix-titulos] corrigidos={len(corrigidos)} erros={len(erros)}")


async def _fix_categoria_bg():
    from ml import auth as ml_auth
    import requests as _req
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    token = ml_auth.get_valid_token()
    headers = {"Authorization": f"Bearer {token}"}

    def _buscar_com_ml_id():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute("SELECT id, ml_id, tipo FROM anuncios WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'")
            return _rows_to_dicts(cur.fetchall(), cur)

    anuncios = _buscar_com_ml_id()
    ml_ids = [a["ml_id"] for a in anuncios]
    id_map = {a["ml_id"]: a for a in anuncios}

    fechados = []
    for i in range(0, len(ml_ids), 20):
        chunk = ml_ids[i:i + 20]
        r = _req.get(
            "https://api.mercadolibre.com/items",
            params={"ids": ",".join(chunk), "attributes": "id,status,sub_status"},
            headers=headers, timeout=15,
        )
        for entry in r.json():
            if isinstance(entry, dict) and entry.get("code") == 200:
                item = entry["body"]
                if item.get("status") == "closed":
                    ml_id = item["id"]
                    an = id_map.get(ml_id, {})
                    if an:
                        fechados.append(an)
        import time; time.sleep(0.3)

    print(f"[fix-categoria] encontrados {len(fechados)} fechados para re-publicar")

    # Limpa ml_id e re-publica
    republicados = []
    erros = []
    for an in fechados:
        try:
            with _get_conn() as conn:
                cur = _cursor(conn)
                cur.execute(f"UPDATE anuncios SET ml_id = NULL, status = 'rascunho', erro_msg = NULL WHERE id = {PH}", [an["id"]])
                conn.commit()
            novo_ml_id = ml_client.publicar_anuncio(an["id"])
            republicados.append({"anuncio_id": an["id"], "novo_ml_id": novo_ml_id})
        except Exception as e:
            erros.append({"anuncio_id": an["id"], "erro": str(e)})
        import time; time.sleep(0.5)

    print(f"[fix-categoria] republicados={len(republicados)} erros={len(erros)}")


@app.post("/api/admin/fix-imagens")
async def fix_imagens(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """Regenera imagens de anúncios publicados com path local (apagado pelo Render) via AI → R2."""
    background_tasks.add_task(_fix_imagens_pillow_bg)
    return {"ok": True, "msg": "Regeneração de imagens iniciada em background (50 por vez)"}


@app.get("/api/admin/debug-cp-query")
async def debug_cp_query(_=Depends(_require_auth)):
    """Testa a query do fix-caca-palavras e retorna quantos itens encontra."""
    def _row_val(row):
        """Extrai primeiro valor de row (dict no PG, tuple no SQLite)."""
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    def _run():
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute("SELECT COUNT(*) as cnt FROM anuncios WHERE ml_id IS NOT NULL AND ml_id != '' AND status != 'deletado'")
            total = _row_val(cur.fetchone())
            cur.execute("SELECT COUNT(*) as cnt FROM kits WHERE nome ILIKE '%palavras%'")
            kits_cp = _row_val(cur.fetchone())
            cur.execute("SELECT COUNT(*) as cnt FROM anuncios WHERE titulo ILIKE '%palavras%' AND ml_id IS NOT NULL")
            titulos_cp = _row_val(cur.fetchone())
            cur.execute("""
                SELECT a.tipo, COUNT(*) as cnt FROM anuncios a
                LEFT JOIN kits k ON a.kit_id = k.id
                WHERE (k.nome ILIKE '%palavras%' OR a.titulo ILIKE '%palavras%')
                  AND a.ml_id IS NOT NULL AND a.status != 'deletado'
                GROUP BY a.tipo
            """)
            por_tipo = {(r["tipo"] if isinstance(r, dict) else r[0]): (r["cnt"] if isinstance(r, dict) else r[1]) for r in cur.fetchall()}
            cur.execute("""
                SELECT a.id, a.tipo, a.titulo FROM anuncios a
                LEFT JOIN kits k ON a.kit_id = k.id
                WHERE (k.nome ILIKE '%palavras%' OR a.titulo ILIKE '%palavras%')
                  AND a.ml_id IS NOT NULL AND a.status != 'deletado' AND a.tipo = 'fisico'
                LIMIT 5
            """)
            fisicos = [{"id": r["id"] if isinstance(r, dict) else r[0], "titulo": (r["titulo"] if isinstance(r, dict) else r[2])[:50]} for r in cur.fetchall()]
            return {"total_anuncios": total, "kits_cp_nome": kits_cp, "anuncios_titulo_palavras": titulos_cp, "por_tipo": por_tipo, "exemplos_fisico": fisicos}
    return await asyncio.to_thread(_run)


@app.post("/api/admin/fix-caca-palavras-digital")
async def fix_caca_palavras_digital(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """Corrige todos os anúncios de caça-palavras: tipo=digital, remove Físico/Impresso do título, categoria MLB1227."""
    background_tasks.add_task(_fix_caca_palavras_digital_bg)
    return {"ok": True, "msg": "Fix caça-palavras digital iniciado em background"}


@app.post("/api/admin/fix-titulos-duplicados")
async def fix_titulos_duplicados(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """Torna únicos os títulos duplicados nos anúncios ativos no ML (adiciona Vol. N)."""
    background_tasks.add_task(_fix_titulos_bg)
    return {"ok": True, "msg": "Correção de títulos duplicados iniciada em background"}


@app.post("/api/admin/limpar-inativos-ml")
async def limpar_inativos_ml(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Fecha no ML e arquiva localmente todos os anúncios com sub_status de problema
    (forbidden, suspended_for_prevention, waiting_for_patch, deleted).
    Não re-publica nada — limpeza total.
    """
    background_tasks.add_task(_limpar_inativos_ml_bg)
    return {"ok": True, "msg": "Limpeza de inativos iniciada em background — verifique os logs"}


async def _limpar_inativos_ml_bg():
    import requests as _req
    from ml import auth as ml_auth, client as ml_client
    from database import _get_conn, _cursor, _rows_to_dicts, atualizar_anuncio

    SUB_STATUS_PROBLEMAS = {"forbidden", "suspended_for_prevention", "waiting_for_patch", "deleted"}

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[limpar-inativos] Token ML inválido: {e}")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _buscar():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                "SELECT id, ml_id FROM anuncios "
                "WHERE ml_id IS NOT NULL AND ml_id != '' "
                "AND status NOT IN ('deletado', 'arquivado')"
            )
            return _rows_to_dicts(cur.fetchall(), cur)

    todos = await asyncio.to_thread(_buscar)
    ml_id_map = {a["ml_id"]: a for a in todos}
    ml_ids = list(ml_id_map.keys())
    print(f"[limpar-inativos] {len(ml_ids)} anúncios para verificar")

    para_fechar = []
    for i in range(0, len(ml_ids), 20):
        batch = ml_ids[i:i+20]
        r = await asyncio.to_thread(
            lambda b=batch: _req.get(
                f"{ml_client.ML_API_BASE}/items",
                params={"ids": ",".join(b), "attributes": "id,status,sub_status"},
                headers=headers, timeout=15,
            )
        )
        await asyncio.sleep(0.3)
        if r.status_code != 200:
            continue
        for entry in r.json():
            item = entry.get("body", {})
            sub = set(item.get("sub_status", []))
            status = item.get("status", "")
            if sub & SUB_STATUS_PROBLEMAS or status in ("closed", "inactive"):
                ml_id = item.get("id", "")
                if ml_id and ml_id in ml_id_map:
                    para_fechar.append(ml_id_map[ml_id])

    print(f"[limpar-inativos] {len(para_fechar)} anúncios problemáticos para fechar")

    fechados = 0
    erros = 0
    for an in para_fechar:
        for tentativa in range(3):
            r = await asyncio.to_thread(
                lambda mid=an["ml_id"]: _req.put(
                    f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                    json={"status": "closed"},
                    headers=headers, timeout=10,
                )
            )
            if r.status_code == 429:
                print(f"[limpar-inativos] rate limit — aguardando 10s (tentativa {tentativa+1})")
                await asyncio.sleep(10)
                continue
            break

        if r.status_code in (200, 400):
            await asyncio.to_thread(lambda aid=an["id"]: atualizar_anuncio(aid, ml_id="", status="arquivado"))
            fechados += 1
        else:
            erros += 1
            print(f"[limpar-inativos] ERRO {an['ml_id']}: {r.status_code} {r.text[:100]}")
        await asyncio.sleep(2)

    print(f"[limpar-inativos] concluído — fechados={fechados} erros={erros}")


@app.post("/api/admin/deletar-forbidden-ml")
async def deletar_forbidden_ml(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """Fecha (sem re-publicar) todos os anúncios under_review/forbidden no ML."""
    background_tasks.add_task(_deletar_forbidden_ml_bg)
    return {"ok": True, "msg": "Deleção de forbidden iniciada em background — verifique os logs"}


async def _deletar_forbidden_ml_bg():
    import requests as _req
    from ml import auth as ml_auth, client as ml_client
    from database import _get_conn, _cursor, _rows_to_dicts, atualizar_anuncio

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[del-forbidden] Token ML inválido: {e}")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _buscar():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                "SELECT id, ml_id FROM anuncios "
                "WHERE ml_id IS NOT NULL AND ml_id != '' "
                "AND status NOT IN ('deletado', 'arquivado')"
            )
            return _rows_to_dicts(cur.fetchall(), cur)

    todos = await asyncio.to_thread(_buscar)
    ml_id_map = {a["ml_id"]: a for a in todos}
    ml_ids = list(ml_id_map.keys())

    forbidden_list = []
    for i in range(0, len(ml_ids), 20):
        batch = ml_ids[i:i+20]
        r = await asyncio.to_thread(
            lambda b=batch: _req.get(
                f"{ml_client.ML_API_BASE}/items",
                params={"ids": ",".join(b), "attributes": "id,sub_status"},
                headers=headers, timeout=15,
            )
        )
        await asyncio.sleep(0.3)
        if r.status_code != 200:
            continue
        for entry in r.json():
            item = entry.get("body", {})
            if "forbidden" in item.get("sub_status", []):
                ml_id = item.get("id", "")
                if ml_id and ml_id in ml_id_map:
                    forbidden_list.append(ml_id_map[ml_id])

    print(f"[del-forbidden] {len(forbidden_list)} forbidden encontrados — fechando sem re-publicar")

    fechados = 0
    erros = 0
    for an in forbidden_list:
        r = await asyncio.to_thread(
            lambda mid=an["ml_id"]: _req.put(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                json={"status": "closed"},
                headers=headers, timeout=10,
            )
        )
        if r.status_code in (200, 400):
            await asyncio.to_thread(lambda aid=an["id"]: atualizar_anuncio(aid, ml_id="", status="arquivado"))
            fechados += 1
        else:
            erros += 1
            print(f"[del-forbidden] ERRO {an['ml_id']}: {r.status_code} {r.text[:100]}")
        await asyncio.sleep(1)

    print(f"[del-forbidden] concluído — fechados={fechados} erros={erros}")


@app.post("/api/admin/corrigir-forbidden-ml")
async def corrigir_forbidden_ml(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """
    Fecha anúncios under_review/forbidden no ML (categoria incorreta) e re-publica
    com a categoria correta (MLB1726 para apostilas físicas).
    """
    background_tasks.add_task(_corrigir_forbidden_ml_bg)
    return {"ok": True, "msg": "Correção de forbidden iniciada em background — verifique os logs"}


async def _corrigir_forbidden_ml_bg():
    import requests as _req
    from ml import auth as ml_auth, client as ml_client
    from database import _get_conn, _cursor, PH, _rows_to_dicts, atualizar_anuncio

    try:
        token = await asyncio.to_thread(ml_auth.get_valid_token)
    except RuntimeError as e:
        print(f"[forbidden] Token ML inválido: {e}")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # 1. Busca todos os anúncios com ml_id do banco
    def _buscar():
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(
                "SELECT id, ml_id, titulo FROM anuncios "
                "WHERE ml_id IS NOT NULL AND ml_id != '' "
                "AND status NOT IN ('deletado', 'arquivado')"
            )
            return _rows_to_dicts(cur.fetchall(), cur)

    todos = await asyncio.to_thread(_buscar)
    ml_id_map = {a["ml_id"]: a for a in todos}
    ml_ids = list(ml_id_map.keys())
    print(f"[forbidden] {len(ml_ids)} anúncios com ml_id para verificar")

    # 2. Busca status em lotes de 20 — filtra forbidden
    forbidden_list = []
    for i in range(0, len(ml_ids), 20):
        batch = ml_ids[i:i+20]
        r = await asyncio.to_thread(
            lambda b=batch: _req.get(
                f"{ml_client.ML_API_BASE}/items",
                params={"ids": ",".join(b), "attributes": "id,status,sub_status"},
                headers=headers, timeout=15,
            )
        )
        await asyncio.sleep(0.3)
        if r.status_code != 200:
            continue
        for entry in r.json():
            item = entry.get("body", {})
            sub = item.get("sub_status", [])
            if "forbidden" in sub:
                ml_id = item.get("id", "")
                if ml_id and ml_id in ml_id_map:
                    forbidden_list.append(ml_id_map[ml_id])

    print(f"[forbidden] {len(forbidden_list)} anúncios forbidden encontrados")

    ok = 0
    erros = 0
    for an in forbidden_list:
        anuncio_id = an["id"]
        ml_id_antigo = an["ml_id"]

        # Fecha no ML
        r_close = await asyncio.to_thread(
            lambda mid=ml_id_antigo: _req.put(
                f"{ml_client.ML_ITEMS_ENDPOINT}/{mid}",
                json={"status": "closed"},
                headers=headers, timeout=10,
            )
        )
        await asyncio.sleep(2)
        if r_close.status_code not in (200, 400):
            erros += 1
            print(f"[forbidden] ERRO ao fechar {ml_id_antigo}: {r_close.status_code} {r_close.text[:150]}")
            continue

        # Limpa ml_id local
        await asyncio.to_thread(lambda aid=anuncio_id: atualizar_anuncio(aid, ml_id="", status="rascunho"))

        # Re-publica (publicar_anuncio usa MLB1726 como fallback para físico)
        try:
            novo_ml_id = await asyncio.to_thread(lambda aid=anuncio_id: ml_client.publicar_anuncio(aid))
            ok += 1
            print(f"[forbidden] OK {ml_id_antigo} → {novo_ml_id} ({an['titulo'][:40]})")
        except Exception as e:
            erros += 1
            print(f"[forbidden] ERRO ao republicar anuncio_id={anuncio_id}: {e}")

        await asyncio.sleep(3)

    print(f"[forbidden] concluído — ok={ok} erros={erros}")


@app.post("/api/admin/fix-categoria-incorreta")
async def fix_categoria_incorreta(background_tasks: BackgroundTasks, _=Depends(_require_auth)):
    """Detecta itens fechados por categoria incorreta no ML e os re-publica."""
    background_tasks.add_task(_fix_categoria_bg)
    return {"ok": True, "msg": "Fix de categoria iniciado em background"}


@app.post("/api/admin/publicar-shopee")
async def publicar_shopee_teste(_=Depends(_require_auth)):
    """Publica 1 anúncio de cada tipo (importado/fisico/digital/kit) que está ativo no ML mas não na Shopee."""
    tokens = await asyncio.to_thread(database.buscar_shopee_tokens)
    if not tokens or not tokens.get("access_token"):
        raise HTTPException(status_code=503, detail="Shopee não conectada — faça OAuth primeiro via /api/shopee/auth")

    from shopee import client as shopee_client
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    def _buscar_um_por_tipo() -> list[dict]:
        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute(f"""
                SELECT * FROM anuncios
                WHERE id IN (
                    SELECT MIN(id) FROM anuncios
                    WHERE ml_id IS NOT NULL AND ml_id != ''
                    AND (shopee_item_id IS NULL OR shopee_item_id = '')
                    AND status != 'deletado'
                    GROUP BY tipo
                )
            """)
            return _rows_to_dicts(cur.fetchall(), cur)

    candidatos = await asyncio.to_thread(_buscar_um_por_tipo)

    publicados = []
    erros = []
    for an in candidatos:
        try:
            item_id = await asyncio.to_thread(shopee_client.publicar_anuncio, an["id"])
            publicados.append({"anuncio_id": an["id"], "tipo": an["tipo"], "titulo": an.get("titulo"), "shopee_item_id": item_id})
        except Exception as e:
            erros.append({"anuncio_id": an["id"], "tipo": an["tipo"], "titulo": an.get("titulo"), "erro": str(e)})
        await asyncio.sleep(0.5)

    return {"publicados": publicados, "erros": erros, "total_candidatos": len(candidatos)}


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

    Se ML_WEBHOOK_SECRET estiver configurado, exige ?secret= na URL
    (registrar o webhook novamente via /api/admin/ml/registrar-webhook).
    """
    webhook_secret = os.getenv("ML_WEBHOOK_SECRET", "")
    if webhook_secret:
        recebido = request.query_params.get("secret", "")
        if not _secrets.compare_digest(recebido, webhook_secret):
            raise HTTPException(status_code=403, detail="secret inválido")

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
            nova_venda = database.salvar_venda(
                ml_order_id=order_id,
                anuncio_id=anuncio_id,
                comprador_nickname=comprador_nick,
                valor=valor,
                quantidade=quantidade,
                data_venda=pedido.get("date_created", ""),
                comprador_id=comprador_id,
            )

            # Boas-vindas automática para venda física nova (digital recebe
            # a mensagem própria com o link do PDF logo abaixo)
            venda = database.buscar_venda_por_order_id(order_id)
            if nova_venda and comprador_id and (venda or {}).get("anuncio_tipo") != "digital":
                ml_messages.enviar_boas_vindas(order_id, comprador_id)

            # Só entrega PDF se for anúncio digital ainda não entregue
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
                    # capa_img: dormente — plugar arte de IA aqui quando houver.
                    # Sem ela, os renderers usam a capa premium CSS.
                    capa_img = None

                    is_cp = apostila.get("topico_slug") == "caca-palavras"
                    if is_cp:
                        from gerar_caca_palavras import gerar_pdf_caca_palavras as _gerar_cp
                        tema        = apostila.get("produto_tema") or "geral"
                        dificuldade = apostila.get("produto_dificuldade") or "medio"
                        num_puzzles = apostila.get("num_exercicios") or 60
                        nome_vol    = apostila.get("produto_nome") or "Caça-Palavras"
                        pdf_path = _gerar_cp(apostila_id, nome_vol, tema, dificuldade, num_puzzles, capa_img=capa_img)
                        database.salvar_conteudo_apostila(apostila_id, "{}", pdf_path)
                    else:
                        from generator import content as _content, pdf as _gen_pdf
                        topico = {
                            "id": apostila["topico_id"],
                            "nome": apostila.get("topico_nome", ""),
                            "descricao": "",
                        }
                        conteudo_json = _content.gerar_conteudo(topico, apostila["num_exercicios"])
                        pdf_path = _gen_pdf.gerar_pdf(apostila_id, topico, conteudo_json, capa_img=capa_img)
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
    webhook_secret = os.getenv("ML_WEBHOOK_SECRET", "")
    if webhook_secret:
        webhook_url += f"?secret={webhook_secret}"

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


@app.get("/api/admin/auditoria-anuncios")
async def auditoria_anuncios(corrigir: int = 0, aplicar_ml: int = 0, _auth=Depends(_require_auth)):
    """Audita todos os anúncios não-deletados contra as regras canônicas.

    Checks: títulos >60 / vazios / duplicados, preço <=0 / fora da tabela,
    kits != 0.85×soma, categorias bloqueadas, anúncios sem imagem.

    - corrigir=1  → aplica correções seguras NO BANCO
    - aplicar_ml=1 → também propaga preço/título/categoria para o ML (requer corrigir=1)
    """
    import time as _time
    import validacao
    from ml.client import _CATS_BLOQUEADAS
    from database import _get_conn, _cursor, PH, _rows_to_dicts

    corrigir = bool(corrigir)
    aplicar_ml = bool(aplicar_ml) and corrigir

    def _put_ml(ml_id: str, payload: dict) -> Optional[str]:
        """PUT no item do ML. Retorna None em sucesso ou mensagem de erro."""
        import requests as _req
        from ml import auth as ml_auth_module
        token = ml_auth_module.get_valid_token()
        r = _req.put(
            f"https://api.mercadolibre.com/items/{ml_id}",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        _time.sleep(0.5)
        return None if r.status_code in (200, 201) else r.text[:200]

    def _run():
        rel = {
            "titulos_vazios": [],
            "titulos_longos": [],
            "titulos_duplicados": [],
            "precos_invalidos": [],
            "precos_fora_tabela": [],
            "kits_preco_errado": [],
            "categorias_bloqueadas": [],
            "categorias_desconhecidas": 0,
            "sem_imagem": [],
        }
        aplicadas = []
        bloqueados = []
        erros_ml = []

        with _get_conn() as conn:
            cur = _cursor(conn)
            cur.execute("""
                SELECT an.id, an.titulo, an.preco, an.tipo, an.status, an.kit_id,
                       an.apostila_id, an.ml_id, an.categoria_id, an.imagem_path,
                       ap.num_exercicios, p.dificuldade
                FROM anuncios an
                LEFT JOIN apostilas ap ON an.apostila_id = ap.id
                LEFT JOIN produtos p ON ap.produto_id = p.id
                WHERE an.status IS NULL OR an.status != 'deletado'
                ORDER BY an.id
            """)
            rows = _rows_to_dicts(cur.fetchall(), cur)

        # --- (c) títulos vazios -------------------------------------------
        for an in rows:
            if not (an.get("titulo") or "").strip():
                rel["titulos_vazios"].append({"id": an["id"], "status": an.get("status")})
                if corrigir:
                    database.atualizar_anuncio(an["id"], status="erro", erro_msg="auditoria: título vazio")
                    bloqueados.append({"id": an["id"], "motivo": "título vazio → status=erro"})

        # --- (a) títulos longos -------------------------------------------
        for an in rows:
            titulo = (an.get("titulo") or "").strip()
            if len(titulo) > 60:
                rel["titulos_longos"].append({"id": an["id"], "len": len(titulo), "titulo": titulo})
                if corrigir:
                    novo = validacao.titulo_unico_no_banco(
                        validacao.fit_titulo(titulo), excluir_id=an["id"]
                    )
                    database.atualizar_anuncio(an["id"], titulo=novo)
                    an["titulo"] = novo
                    aplicadas.append({"id": an["id"], "campo": "titulo", "de": titulo, "para": novo})
                    if aplicar_ml and an.get("ml_id") and an.get("status") == "publicado":
                        err = _put_ml(an["ml_id"], {"title": novo})
                        if err:
                            erros_ml.append({"id": an["id"], "ml_id": an["ml_id"], "erro": err})

        # --- (b) títulos duplicados (rascunhos E publicados) ---------------
        por_titulo: dict = {}
        for an in rows:
            chave = (an.get("titulo") or "").strip().lower()
            if chave:
                por_titulo.setdefault(chave, []).append(an)
        for chave, grupo in por_titulo.items():
            if len(grupo) <= 1:
                continue
            grupo.sort(key=lambda a: a["id"])
            ids = [a["id"] for a in grupo]
            rel["titulos_duplicados"].append({"titulo": grupo[0]["titulo"], "ids": ids})
            if corrigir:
                # mantém o mais antigo; renomeia os demais
                for an in grupo[1:]:
                    novo = validacao.titulo_unico_no_banco(an["titulo"], excluir_id=an["id"])
                    if novo == an["titulo"]:
                        continue
                    database.atualizar_anuncio(an["id"], titulo=novo)
                    an["titulo"] = novo
                    aplicadas.append({"id": an["id"], "campo": "titulo", "de": grupo[0]["titulo"], "para": novo})
                    if aplicar_ml and an.get("ml_id") and an.get("status") == "publicado":
                        err = _put_ml(an["ml_id"], {"title": novo})
                        if err:
                            erros_ml.append({"id": an["id"], "ml_id": an["ml_id"], "erro": err})

        # --- (d) preços ----------------------------------------------------
        for an in rows:
            preco = float(an.get("preco") or 0)
            tipo = an.get("tipo") or "fisico"
            if preco <= 0:
                rel["precos_invalidos"].append({"id": an["id"], "preco": preco, "status": an.get("status")})
                if corrigir:
                    database.atualizar_anuncio(an["id"], status="erro", erro_msg=f"auditoria: preço inválido ({preco})")
                    bloqueados.append({"id": an["id"], "motivo": f"preço {preco} → status=erro"})
                continue
            if an.get("kit_id") or tipo == "importado":
                continue  # kit: check (e); importado: espelho do ML, report-only via faixa
            canonico = pricing.preco_canonico(
                tipo, an.get("num_exercicios"), an.get("dificuldade")
            )
            # Sem dificuldade registrada mas preço bate com a tabela de
            # caça-palavras → provável CP sem backfill; não flagra.
            if not an.get("dificuldade") and preco in pricing.PRECOS_CACA_PALAVRAS.values():
                continue
            if canonico and abs(preco - canonico) > 0.01:
                rel["precos_fora_tabela"].append(
                    {"id": an["id"], "tipo": tipo, "preco": preco, "esperado": canonico}
                )
                if corrigir:
                    database.atualizar_anuncio(an["id"], preco=canonico)
                    aplicadas.append({"id": an["id"], "campo": "preco", "de": preco, "para": canonico})
                    if aplicar_ml and an.get("ml_id") and an.get("status") == "publicado":
                        try:
                            ml_client.atualizar_preco_ml(an["ml_id"], canonico)
                            _time.sleep(0.5)
                        except Exception as e:
                            erros_ml.append({"id": an["id"], "ml_id": an["ml_id"], "erro": str(e)[:200]})

        # --- (e) kits: preço deve ser 0.85 × soma dos individuais ----------
        kits_esperado: dict = {}
        with _get_conn() as conn:
            cur = _cursor(conn)
            # tipo != 'importado': anúncios importados do ML têm preço definido
            # manualmente — a regra 0.85×soma NÃO se aplica a eles
            cur.execute("""
                SELECT an.id, an.kit_id, an.preco, an.ml_id, an.status, k.apostila_ids
                FROM anuncios an
                JOIN kits k ON an.kit_id = k.id
                WHERE (an.status IS NULL OR an.status != 'deletado')
                  AND an.tipo != 'importado'
            """)
            kit_rows = _rows_to_dicts(cur.fetchall(), cur)
            for row in kit_rows:
                kit_id = row["kit_id"]
                if kit_id not in kits_esperado:
                    try:
                        apostila_ids = json.loads(row.get("apostila_ids") or "[]")
                    except Exception:
                        apostila_ids = []
                    total = 0.0
                    for aid in apostila_ids:
                        # Kit de caça-palavras: individual = tabela CP por dificuldade
                        cur.execute(f"""
                            SELECT p.dificuldade FROM apostilas ap
                            LEFT JOIN produtos p ON ap.produto_id = p.id
                            WHERE ap.id = {PH}
                        """, (aid,))
                        rd = cur.fetchone()
                        dificuldade = (rd["dificuldade"] if rd else None) or ""
                        preco_cp = pricing.PRECOS_CACA_PALAVRAS.get(dificuldade.lower())
                        if preco_cp:
                            total += preco_cp
                            continue
                        cur.execute(f"""
                            SELECT preco FROM anuncios
                            WHERE apostila_id = {PH}
                              AND tipo IN ('fisico', 'importado')
                              AND status NOT IN ('deletado')
                              AND preco > 50
                            ORDER BY preco DESC LIMIT 1
                        """, (aid,))
                        r = cur.fetchone()
                        total += float(r["preco"]) if r and r["preco"] else pricing.PRECO_FALLBACK_INDIVIDUAL
                    kits_esperado[kit_id] = pricing.preco_kit(total)
        for row in kit_rows:
            esperado = kits_esperado.get(row["kit_id"])
            preco = float(row.get("preco") or 0)
            if esperado and preco > 0 and abs(preco - esperado) > 0.01:
                rel["kits_preco_errado"].append(
                    {"id": row["id"], "kit_id": row["kit_id"], "preco": preco, "esperado": esperado}
                )
                if corrigir:
                    database.atualizar_anuncio(row["id"], preco=esperado)
                    aplicadas.append({"id": row["id"], "campo": "preco", "de": preco, "para": esperado})
                    if aplicar_ml and row.get("ml_id") and row.get("status") == "publicado":
                        try:
                            ml_client.atualizar_preco_ml(row["ml_id"], esperado)
                            _time.sleep(0.5)
                        except Exception as e:
                            erros_ml.append({"id": row["id"], "ml_id": row["ml_id"], "erro": str(e)[:200]})

        # --- (f) categorias -------------------------------------------------
        for an in rows:
            cat = an.get("categoria_id")
            if not cat:
                rel["categorias_desconhecidas"] += 1
            elif cat in _CATS_BLOQUEADAS:
                rel["categorias_bloqueadas"].append(
                    {"id": an["id"], "ml_id": an.get("ml_id"), "categoria": cat}
                )
        if aplicar_ml and rel["categorias_bloqueadas"]:
            try:
                resultado_cat = ml_client.fix_categorias_ml()
                aplicadas.append({"campo": "categorias", "resultado": {
                    "atualizados": len(resultado_cat.get("atualizados", [])),
                    "erros": len(resultado_cat.get("erros", [])),
                }})
            except Exception as e:
                erros_ml.append({"campo": "categorias", "erro": str(e)[:200]})

        # --- (g) sem imagem (report-only; publicação gera on-demand) -------
        for an in rows:
            if not (an.get("imagem_path") or "").strip():
                rel["sem_imagem"].append({
                    "id": an["id"], "status": an.get("status"),
                    "tem_fonte_para_gerar": bool(an.get("apostila_id") or an.get("kit_id")),
                })

        resumo = {k: (v if isinstance(v, int) else len(v)) for k, v in rel.items()}
        resumo["total_anuncios"] = len(rows)
        return {
            "modo": {"corrigir": corrigir, "aplicar_ml": aplicar_ml},
            "resumo": resumo,
            "problemas": rel,
            "correcoes_aplicadas": aplicadas,
            "bloqueados": bloqueados,
            "erros_ml": erros_ml,
        }

    return await asyncio.to_thread(_run)


# ---------------------------------------------------------------------------
# Dev runner
# ---------------------------------------------------------------------------

@app.get("/api/youtube/status")
async def youtube_status(_auth=Depends(_require_auth)):
    from youtube import auth as yt_auth
    return {"autorizado": yt_auth.is_authorized()}


@app.get("/api/youtube/auth")
async def youtube_auth_url(_auth=Depends(_require_auth)):
    from youtube import auth as yt_auth
    if not yt_auth.CLIENT_ID or not yt_auth.CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET não configurados no .env")
    url = yt_auth.get_auth_url()
    return {"url": url}


@app.get("/api/youtube/callback")
async def youtube_callback(code: str):
    from youtube import auth as yt_auth
    try:
        yt_auth.exchange_code(code)
        return {"status": "autorizado", "mensagem": "YouTube conectado com sucesso! Pode fechar esta aba."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/anuncios/{anuncio_id}/gerar-clipe")
async def gerar_clipe_anuncio(
    anuncio_id: int,
    modo: str = "ken_burns",
    publicar_ml: bool = True,
    _auth=Depends(_require_auth),
):
    """
    Gera clipe de vídeo para o anúncio, faz upload para R2 e opcionalmente
    envia para o ML (Decola). modo='ken_burns' (padrão, local) ou 'svd' (HuggingFace).
    """
    from generator import video as _video
    from ml import auth as ml_auth_module
    import storage as _storage
    import requests as _req

    anuncio = database.buscar_anuncio_por_id(anuncio_id)
    if not anuncio:
        raise HTTPException(status_code=404, detail="Anúncio não encontrado")

    imagem_path = anuncio.get("imagem_path") or ""
    if not imagem_path:
        raise HTTPException(status_code=400, detail="Anúncio sem imagem — gere as capas primeiro")

    # Gera o clipe localmente com nome único por anúncio
    output_path = str(_video.OUTPUT_DIR / f"anuncio_{anuncio_id}_{modo}.mp4")
    try:
        local_video = await asyncio.to_thread(_video.gerar_clipe, imagem_path, output_path, modo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar clipe: {e}")

    # Upload para R2 com chave única
    r2_key = f"anuncio_{anuncio_id}_{modo}.mp4"
    r2_url = await asyncio.to_thread(_storage.upload_video, local_video, r2_key)

    result = {"anuncio_id": anuncio_id, "video_url": r2_url, "modo": modo}

    # Upload para YouTube (necessário para setar video_id no ML)
    youtube_id = None
    from youtube import auth as yt_auth
    from youtube import upload as yt_upload
    if yt_auth.is_authorized():
        titulo_anuncio = anuncio.get("titulo", f"CogniVita – Anúncio {anuncio_id}")
        try:
            youtube_id = await asyncio.to_thread(
                yt_upload.upload_video,
                local_video,
                titulo_anuncio,
                "Apostila física CogniVita – Exercícios cognitivos impressos.",
                "unlisted",
            )
            result["youtube_id"] = youtube_id
            result["youtube_url"] = f"https://youtu.be/{youtube_id}"
        except Exception as e:
            result["youtube_error"] = str(e)
    else:
        result["youtube_status"] = "não autorizado — acesse /api/youtube/auth"

    # Envia video_id para o ML
    ml_id = anuncio.get("ml_id")
    if publicar_ml and ml_id and youtube_id:
        try:
            token = await asyncio.to_thread(ml_auth_module.get_valid_token)
            resp = _req.put(
                f"https://api.mercadolibre.com/items/{ml_id}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"video_id": youtube_id},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                result["ml_status"] = "video_id enviado"
            else:
                result["ml_status"] = f"erro {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            result["ml_status"] = f"erro: {e}"
    elif not youtube_id:
        result["ml_status"] = "aguardando YouTube"
    else:
        result["ml_status"] = "não enviado (sem ml_id ou publicar_ml=false)"

    return result


@app.post("/api/admin/topicos/{topico_id}/gerar-clipes")
async def gerar_clipes_topico(
    topico_id: int,
    modo: str = "ken_burns",
    publicar_ml: bool = True,
    _auth=Depends(_require_auth),
):
    """Gera clipes para todos os anúncios publicados de um tópico."""
    anuncios = database.listar_anuncios(topico_id=topico_id, status="publicado", limite=999)
    if not anuncios:
        raise HTTPException(status_code=404, detail="Nenhum anúncio publicado para este tópico")

    from generator import video as _video
    from ml import auth as ml_auth_module
    import storage as _storage
    import requests as _req

    resultados = []
    for anuncio in anuncios:
        anuncio_id = anuncio["id"]
        imagem_path = anuncio.get("imagem_path") or ""
        if not imagem_path:
            resultados.append({"anuncio_id": anuncio_id, "status": "sem imagem"})
            continue
        try:
            local_video = await asyncio.to_thread(_video.gerar_clipe, imagem_path, None, modo)
            r2_url = await asyncio.to_thread(_storage.upload_video, local_video)
            ml_id = anuncio.get("ml_id")
            ml_status = "sem ml_id"
            if publicar_ml and ml_id:
                token = await asyncio.to_thread(ml_auth_module.get_valid_token)
                resp = _req.put(
                    f"https://api.mercadolibre.com/items/{ml_id}",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"video": {"url": r2_url}},
                    timeout=30,
                )
                ml_status = "enviado" if resp.status_code in (200, 201) else f"erro {resp.status_code}"
            resultados.append({"anuncio_id": anuncio_id, "video_url": r2_url, "ml_status": ml_status})
        except Exception as e:
            resultados.append({"anuncio_id": anuncio_id, "status": f"erro: {e}"})

    ok = sum(1 for r in resultados if "video_url" in r)
    return {"total": len(resultados), "ok": ok, "resultados": resultados}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
