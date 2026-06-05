# Multi-Marca Fase 1: Fundação — DB + Migração + CRUD API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o novo schema multi-marca no PostgreSQL, migrar dados CogniVita para ele, e expor endpoints CRUD básicos para marcas, produtos e listagens.

**Architecture:** Novas tabelas coexistem com as antigas (apostilas, kits, anuncios) durante a transição. A migração é um script Python idempotente que pode ser re-executado com segurança. A API ganha novos endpoints `/api/v2/` sem remover os existentes.

**Tech Stack:** FastAPI, psycopg2, PostgreSQL (Render), Python 3.11

---

## Arquivos

| Ação | Arquivo | Responsabilidade |
|---|---|---|
| Criar | `migrations/001_multi_marca.sql` | DDL das 5 novas tabelas |
| Criar | `migrations/002_migrar_cognivita.py` | Popula novas tabelas com dados CogniVita |
| Modificar | `database.py` | Funções CRUD para novas tabelas |
| Modificar | `api.py` | Endpoints `/api/v2/marcas`, `/api/v2/produtos`, `/api/v2/listagens` |

---

## Task 1: DDL das novas tabelas

**Files:**
- Criar: `migrations/001_multi_marca.sql`

- [ ] **Criar o arquivo SQL**

```sql
-- migrations/001_multi_marca.sql
-- Idempotente: usa IF NOT EXISTS em tudo

CREATE TABLE IF NOT EXISTS marcas (
    id          SERIAL PRIMARY KEY,
    nome        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    cor_principal TEXT DEFAULT '#1B6B4A',
    logo_url    TEXT,
    ativo       BOOLEAN DEFAULT true,
    criado_em   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contas_plataforma (
    id          SERIAL PRIMARY KEY,
    marca_id    INTEGER NOT NULL REFERENCES marcas(id),
    plataforma  TEXT NOT NULL CHECK (plataforma IN ('ml', 'shopee', 'amazon')),
    credenciais JSONB NOT NULL DEFAULT '{}',
    ativo       BOOLEAN DEFAULT true,
    criado_em   TIMESTAMP DEFAULT NOW(),
    UNIQUE (marca_id, plataforma)
);

CREATE TABLE IF NOT EXISTS produtos (
    id              SERIAL PRIMARY KEY,
    marca_id        INTEGER NOT NULL REFERENCES marcas(id),
    nome            TEXT NOT NULL,
    descricao       TEXT,
    tipo            TEXT NOT NULL DEFAULT 'proprio' CHECK (tipo IN ('proprio', 'revenda')),
    preco_base      NUMERIC(10,2),
    custo_producao  NUMERIC(10,2),
    imagem_url      TEXT,
    conteudo_path   TEXT,
    ativo           BOOLEAN DEFAULT true,
    criado_em       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS listagens (
    id                  SERIAL PRIMARY KEY,
    produto_id          INTEGER NOT NULL REFERENCES produtos(id),
    conta_id            INTEGER NOT NULL REFERENCES contas_plataforma(id),
    titulo              TEXT NOT NULL,
    preco               NUMERIC(10,2),
    status              TEXT DEFAULT 'rascunho'
                            CHECK (status IN ('rascunho','publicado','pausado','arquivado','deletado')),
    plataforma_item_id  TEXT,
    imagem_url          TEXT,
    erro_msg            TEXT,
    criado_em           TIMESTAMP DEFAULT NOW(),
    atualizado_em       TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pedidos (
    id                    SERIAL PRIMARY KEY,
    listagem_id           INTEGER NOT NULL REFERENCES listagens(id),
    plataforma_pedido_id  TEXT NOT NULL,
    status                TEXT DEFAULT 'novo'
                              CHECK (status IN ('novo','pdf_gerado','enviado_grafica','entregue','cancelado')),
    valor                 NUMERIC(10,2),
    nome_cliente          TEXT,
    endereco_entrega      JSONB DEFAULT '{}',
    pdf_gerado            BOOLEAN DEFAULT false,
    enviado_grafica       BOOLEAN DEFAULT false,
    criado_em             TIMESTAMP DEFAULT NOW(),
    atualizado_em         TIMESTAMP DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_produtos_marca ON produtos(marca_id);
CREATE INDEX IF NOT EXISTS idx_listagens_produto ON listagens(produto_id);
CREATE INDEX IF NOT EXISTS idx_listagens_conta ON listagens(conta_id);
CREATE INDEX IF NOT EXISTS idx_listagens_status ON listagens(status);
CREATE INDEX IF NOT EXISTS idx_pedidos_listagem ON pedidos(listagem_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_status ON pedidos(status);
```

- [ ] **Executar o SQL no banco de produção via psql ou endpoint admin**

Adicionar em `database.py` na função `criar_tabelas()`, ao final:

```python
# No final da função criar_tabelas(), após o bloco existente:
sqls_v2 = [
    open(os.path.join(os.path.dirname(__file__), "migrations", "001_multi_marca.sql")).read()
]
for sql in sqls_v2:
    try:
        cur.execute(sql)
    except Exception as e:
        print(f"[DB] migrations/001: {e}")
conn.commit()
```

- [ ] **Verificar criação das tabelas**

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('marcas','contas_plataforma','produtos','listagens','pedidos');
-- Esperado: 5 linhas
```

- [ ] **Commit**

```bash
git add migrations/001_multi_marca.sql database.py
git commit -m "feat: add multi-brand schema (marcas, contas_plataforma, produtos, listagens, pedidos)"
```

---

## Task 2: Script de migração CogniVita

**Files:**
- Criar: `migrations/002_migrar_cognivita.py`

- [ ] **Criar o script de migração**

```python
# migrations/002_migrar_cognivita.py
"""
Migra dados CogniVita das tabelas legadas para o novo schema multi-marca.
Idempotente: verifica existência antes de inserir (ON CONFLICT DO NOTHING).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

def run():
    with database._get_conn() as conn:
        cur = database._cursor(conn)

        # 1. Cria marca CogniVita
        cur.execute("""
            INSERT INTO marcas (nome, slug, cor_principal)
            VALUES ('CogniVita', 'cognivita', '#1B6B4A')
            ON CONFLICT (slug) DO NOTHING
        """)
        cur.execute("SELECT id FROM marcas WHERE slug = 'cognivita'")
        row = cur.fetchone()
        marca_id = row["id"] if isinstance(row, dict) else row[0]
        print(f"[migrar] marca_id={marca_id}")

        # 2. Cria conta ML da CogniVita (credenciais virão do env)
        import json, os as _os
        ml_creds = {
            "client_id": _os.getenv("ML_CLIENT_ID", ""),
            "client_secret": _os.getenv("ML_CLIENT_SECRET", ""),
        }
        # Busca token atual do banco de tokens ML legado
        cur.execute("SELECT access_token, refresh_token, expires_at FROM ml_tokens ORDER BY id DESC LIMIT 1")
        tok = cur.fetchone()
        if tok:
            t = tok if not isinstance(tok, dict) else tok
            ml_creds["access_token"] = t["access_token"] if isinstance(t, dict) else t[0]
            ml_creds["refresh_token"] = t["refresh_token"] if isinstance(t, dict) else t[1]

        cur.execute("""
            INSERT INTO contas_plataforma (marca_id, plataforma, credenciais)
            VALUES (%s, 'ml', %s)
            ON CONFLICT (marca_id, plataforma) DO NOTHING
        """, [marca_id, json.dumps(ml_creds)])
        cur.execute("SELECT id FROM contas_plataforma WHERE marca_id = %s AND plataforma = 'ml'", [marca_id])
        row = cur.fetchone()
        conta_id = row["id"] if isinstance(row, dict) else row[0]
        print(f"[migrar] conta_ml_id={conta_id}")

        # 3. Migra apostilas individuais → produtos
        cur.execute("""
            SELECT a.id, a.num_exercicios, t.nome as topico_nome, a.imagem_path
            FROM apostilas a
            LEFT JOIN topicos t ON a.topico_id = t.id
        """)
        apostilas = cur.fetchall()
        apostila_produto_map = {}
        for ap in apostilas:
            ap = dict(ap) if not isinstance(ap, dict) else ap
            nome = f"Apostila {ap.get('topico_nome','Cognitiva')} {ap.get('num_exercicios',60)} Exercícios"
            cur.execute("""
                INSERT INTO produtos (marca_id, nome, tipo, preco_base, imagem_url)
                SELECT %s, %s, 'proprio', an.preco, %s
                FROM anuncios an WHERE an.apostila_id = %s AND an.status != 'deletado'
                LIMIT 1
                ON CONFLICT DO NOTHING
                RETURNING id
            """, [marca_id, nome[:120], ap.get("imagem_path",""), ap["id"]])
            row = cur.fetchone()
            if row:
                pid = row["id"] if isinstance(row, dict) else row[0]
                apostila_produto_map[ap["id"]] = pid

        # 4. Migra anúncios ativos → listagens
        cur.execute("""
            SELECT id, apostila_id, kit_id, titulo, preco, status, ml_id, imagem_path
            FROM anuncios
            WHERE status NOT IN ('deletado','arquivado') AND ml_id IS NOT NULL
        """)
        anuncios = cur.fetchall()
        migrados = 0
        for an in anuncios:
            an = dict(an) if not isinstance(an, dict) else an
            prod_id = apostila_produto_map.get(an.get("apostila_id"))
            if not prod_id:
                continue
            cur.execute("""
                INSERT INTO listagens (produto_id, conta_id, titulo, preco, status, plataforma_item_id, imagem_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, [
                prod_id, conta_id,
                (an.get("titulo") or "")[:200],
                an.get("preco") or 0,
                "publicado" if an.get("status") == "publicado" else "rascunho",
                an.get("ml_id") or "",
                an.get("imagem_path") or "",
            ])
            migrados += 1

        conn.commit()
        print(f"[migrar] produtos={len(apostila_produto_map)} listagens={migrados}")
        print("[migrar] concluído ✓")

if __name__ == "__main__":
    run()
```

- [ ] **Adicionar endpoint admin para executar a migração**

Em `api.py`, adicionar após os outros endpoints admin:

```python
@app.post("/api/admin/migrar-cognivita")
async def migrar_cognivita(_=Depends(_require_auth)):
    """Executa migração CogniVita → novo schema multi-marca."""
    def _run():
        import importlib.util, os
        spec = importlib.util.spec_from_file_location(
            "migrar",
            os.path.join(os.path.dirname(__file__), "migrations", "002_migrar_cognivita.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.run()
        return {"ok": True}
    return await asyncio.to_thread(_run)
```

- [ ] **Commit**

```bash
git add migrations/002_migrar_cognivita.py api.py
git commit -m "feat: add CogniVita migration script to new multi-brand schema"
```

---

## Task 3: Funções CRUD no database.py

**Files:**
- Modificar: `database.py`

- [ ] **Adicionar funções CRUD para as novas tabelas no final de database.py**

```python
# ── Multi-marca: CRUD ─────────────────────────────────────────────────────────

def listar_marcas() -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute("SELECT * FROM marcas WHERE ativo = true ORDER BY nome")
        return _rows_to_dicts(cur.fetchall(), cur)


def criar_marca(nome: str, slug: str, cor_principal: str = "#1B6B4A", logo_url: str = "") -> int:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"INSERT INTO marcas (nome, slug, cor_principal, logo_url) VALUES ({PH},{PH},{PH},{PH}) RETURNING id",
            [nome, slug, cor_principal, logo_url]
        )
        row = cur.fetchone()
        conn.commit()
        return row["id"] if isinstance(row, dict) else row[0]


def listar_contas(marca_id: int = None) -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        if marca_id:
            cur.execute("SELECT * FROM contas_plataforma WHERE marca_id = %s AND ativo = true", [marca_id])
        else:
            cur.execute("SELECT * FROM contas_plataforma WHERE ativo = true ORDER BY marca_id")
        return _rows_to_dicts(cur.fetchall(), cur)


def criar_conta(marca_id: int, plataforma: str, credenciais: dict) -> int:
    import json
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"INSERT INTO contas_plataforma (marca_id, plataforma, credenciais) VALUES ({PH},{PH},{PH}) RETURNING id",
            [marca_id, plataforma, json.dumps(credenciais)]
        )
        row = cur.fetchone()
        conn.commit()
        return row["id"] if isinstance(row, dict) else row[0]


def atualizar_credenciais(conta_id: int, credenciais: dict):
    import json
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"UPDATE contas_plataforma SET credenciais = {PH} WHERE id = {PH}",
            [json.dumps(credenciais), conta_id]
        )
        conn.commit()


def listar_produtos(marca_id: int = None, apenas_ativos: bool = True) -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = "SELECT p.*, m.nome as marca_nome FROM produtos p JOIN marcas m ON p.marca_id = m.id WHERE 1=1"
        params = []
        if marca_id:
            sql += f" AND p.marca_id = {PH}"; params.append(marca_id)
        if apenas_ativos:
            sql += " AND p.ativo = true"
        sql += " ORDER BY p.criado_em DESC"
        cur.execute(sql, params)
        return _rows_to_dicts(cur.fetchall(), cur)


def criar_produto(marca_id: int, nome: str, descricao: str = "", tipo: str = "proprio",
                  preco_base: float = 0, custo_producao: float = 0,
                  imagem_url: str = "", conteudo_path: str = "") -> int:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"""INSERT INTO produtos (marca_id, nome, descricao, tipo, preco_base, custo_producao, imagem_url, conteudo_path)
                VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH}) RETURNING id""",
            [marca_id, nome, descricao, tipo, preco_base, custo_producao, imagem_url, conteudo_path]
        )
        row = cur.fetchone()
        conn.commit()
        return row["id"] if isinstance(row, dict) else row[0]


def atualizar_produto(produto_id: int, **kwargs):
    campos_permitidos = {"nome","descricao","preco_base","custo_producao","imagem_url","conteudo_path","ativo"}
    updates = {k: v for k, v in kwargs.items() if k in campos_permitidos}
    if not updates:
        return
    with _get_conn() as conn:
        cur = _cursor(conn)
        sets = ", ".join(f"{k} = {PH}" for k in updates)
        cur.execute(f"UPDATE produtos SET {sets} WHERE id = {PH}", list(updates.values()) + [produto_id])
        conn.commit()


def listar_listagens(produto_id: int = None, conta_id: int = None,
                     status: str = None, marca_id: int = None) -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = """
            SELECT l.*, p.nome as produto_nome, m.slug as marca_slug,
                   cp.plataforma
            FROM listagens l
            JOIN produtos p ON l.produto_id = p.id
            JOIN marcas m ON p.marca_id = m.id
            JOIN contas_plataforma cp ON l.conta_id = cp.id
            WHERE l.status != 'deletado'
        """
        params = []
        if produto_id:
            sql += f" AND l.produto_id = {PH}"; params.append(produto_id)
        if conta_id:
            sql += f" AND l.conta_id = {PH}"; params.append(conta_id)
        if status:
            sql += f" AND l.status = {PH}"; params.append(status)
        if marca_id:
            sql += f" AND p.marca_id = {PH}"; params.append(marca_id)
        sql += " ORDER BY l.criado_em DESC"
        cur.execute(sql, params)
        return _rows_to_dicts(cur.fetchall(), cur)


def criar_listagem(produto_id: int, conta_id: int, titulo: str,
                   preco: float, imagem_url: str = "") -> int:
    with _get_conn() as conn:
        cur = _cursor(conn)
        cur.execute(
            f"""INSERT INTO listagens (produto_id, conta_id, titulo, preco, imagem_url)
                VALUES ({PH},{PH},{PH},{PH},{PH}) RETURNING id""",
            [produto_id, conta_id, titulo, preco, imagem_url]
        )
        row = cur.fetchone()
        conn.commit()
        return row["id"] if isinstance(row, dict) else row[0]


def atualizar_listagem(listagem_id: int, **kwargs):
    campos_permitidos = {"titulo","preco","status","plataforma_item_id","imagem_url","erro_msg","atualizado_em"}
    updates = {k: v for k, v in kwargs.items() if k in campos_permitidos}
    if not updates:
        return
    updates["atualizado_em"] = "NOW()"
    with _get_conn() as conn:
        cur = _cursor(conn)
        sets = []
        vals = []
        for k, v in updates.items():
            if v == "NOW()":
                sets.append(f"{k} = NOW()")
            else:
                sets.append(f"{k} = {PH}")
                vals.append(v)
        cur.execute(f"UPDATE listagens SET {', '.join(sets)} WHERE id = {PH}", vals + [listagem_id])
        conn.commit()


def listar_pedidos(status: str = None, marca_id: int = None, limite: int = 100) -> list:
    with _get_conn() as conn:
        cur = _cursor(conn)
        sql = """
            SELECT pe.*, l.titulo as listagem_titulo, cp.plataforma, m.nome as marca_nome
            FROM pedidos pe
            JOIN listagens l ON pe.listagem_id = l.id
            JOIN contas_plataforma cp ON l.conta_id = cp.id
            JOIN produtos p ON l.produto_id = p.id
            JOIN marcas m ON p.marca_id = m.id
            WHERE 1=1
        """
        params = []
        if status:
            sql += f" AND pe.status = {PH}"; params.append(status)
        if marca_id:
            sql += f" AND p.marca_id = {PH}"; params.append(marca_id)
        sql += f" ORDER BY pe.criado_em DESC LIMIT {PH}"; params.append(limite)
        cur.execute(sql, params)
        return _rows_to_dicts(cur.fetchall(), cur)
```

- [ ] **Commit**

```bash
git add database.py
git commit -m "feat: add multi-brand CRUD functions to database.py"
```

---

## Task 4: Endpoints API v2

**Files:**
- Modificar: `api.py`

- [ ] **Adicionar endpoints `/api/v2/` no api.py**

Adicionar antes do bloco `if __name__ == "__main__"` (ou no final do arquivo, antes de qualquer `uvicorn.run`):

```python
# ── API v2: Multi-marca ───────────────────────────────────────────────────────

@app.get("/api/v2/marcas")
async def v2_listar_marcas(_=Depends(_require_auth)):
    return await asyncio.to_thread(database.listar_marcas)


@app.post("/api/v2/marcas")
async def v2_criar_marca(body: dict, _=Depends(_require_auth)):
    nome = body.get("nome", "").strip()
    slug = body.get("slug", "").strip().lower().replace(" ", "-")
    if not nome or not slug:
        raise HTTPException(status_code=400, detail="nome e slug obrigatórios")
    mid = await asyncio.to_thread(
        database.criar_marca, nome, slug,
        body.get("cor_principal", "#1B6B4A"),
        body.get("logo_url", ""),
    )
    return {"id": mid, "slug": slug}


@app.get("/api/v2/marcas/{marca_id}/contas")
async def v2_listar_contas(marca_id: int, _=Depends(_require_auth)):
    return await asyncio.to_thread(database.listar_contas, marca_id)


@app.post("/api/v2/marcas/{marca_id}/contas")
async def v2_criar_conta(marca_id: int, body: dict, _=Depends(_require_auth)):
    plataforma = body.get("plataforma", "")
    if plataforma not in ("ml", "shopee", "amazon"):
        raise HTTPException(status_code=400, detail="plataforma inválida")
    cid = await asyncio.to_thread(
        database.criar_conta, marca_id, plataforma, body.get("credenciais", {})
    )
    return {"id": cid}


@app.get("/api/v2/produtos")
async def v2_listar_produtos(marca_id: int = None, _=Depends(_require_auth)):
    return await asyncio.to_thread(database.listar_produtos, marca_id)


@app.post("/api/v2/produtos")
async def v2_criar_produto(body: dict, _=Depends(_require_auth)):
    marca_id = body.get("marca_id")
    nome = (body.get("nome") or "").strip()
    if not marca_id or not nome:
        raise HTTPException(status_code=400, detail="marca_id e nome obrigatórios")
    pid = await asyncio.to_thread(
        database.criar_produto,
        marca_id, nome,
        body.get("descricao", ""),
        body.get("tipo", "proprio"),
        float(body.get("preco_base") or 0),
        float(body.get("custo_producao") or 0),
        body.get("imagem_url", ""),
        body.get("conteudo_path", ""),
    )
    return {"id": pid}


@app.patch("/api/v2/produtos/{produto_id}")
async def v2_atualizar_produto(produto_id: int, body: dict, _=Depends(_require_auth)):
    await asyncio.to_thread(database.atualizar_produto, produto_id, **body)
    return {"ok": True}


@app.get("/api/v2/listagens")
async def v2_listar_listagens(
    produto_id: int = None, conta_id: int = None,
    status: str = None, marca_id: int = None,
    _=Depends(_require_auth)
):
    return await asyncio.to_thread(
        database.listar_listagens, produto_id, conta_id, status, marca_id
    )


@app.post("/api/v2/listagens")
async def v2_criar_listagem(body: dict, _=Depends(_require_auth)):
    produto_id = body.get("produto_id")
    conta_id = body.get("conta_id")
    titulo = (body.get("titulo") or "").strip()
    if not produto_id or not conta_id or not titulo:
        raise HTTPException(status_code=400, detail="produto_id, conta_id e titulo obrigatórios")
    lid = await asyncio.to_thread(
        database.criar_listagem,
        produto_id, conta_id, titulo,
        float(body.get("preco") or 0),
        body.get("imagem_url", ""),
    )
    return {"id": lid}


@app.patch("/api/v2/listagens/{listagem_id}")
async def v2_atualizar_listagem(listagem_id: int, body: dict, _=Depends(_require_auth)):
    await asyncio.to_thread(database.atualizar_listagem, listagem_id, **body)
    return {"ok": True}


@app.get("/api/v2/pedidos")
async def v2_listar_pedidos(
    status: str = None, marca_id: int = None, limite: int = 100,
    _=Depends(_require_auth)
):
    return await asyncio.to_thread(database.listar_pedidos, status, marca_id, limite)


@app.get("/api/v2/stats")
async def v2_stats(_=Depends(_require_auth)):
    def _run():
        with database._get_conn() as conn:
            cur = database._cursor(conn)
            cur.execute("SELECT COUNT(*) as cnt FROM marcas WHERE ativo = true")
            marcas = (cur.fetchone() or {})
            cur.execute("SELECT COUNT(*) as cnt FROM produtos WHERE ativo = true")
            produtos = (cur.fetchone() or {})
            cur.execute("SELECT COUNT(*) as cnt FROM listagens WHERE status = 'publicado'")
            listagens = (cur.fetchone() or {})
            cur.execute("SELECT COUNT(*) as cnt FROM pedidos WHERE status = 'novo'")
            pedidos = (cur.fetchone() or {})
            def val(r): return r["cnt"] if isinstance(r, dict) else r[0]
            return {
                "marcas": val(marcas),
                "produtos": val(produtos),
                "listagens_publicadas": val(listagens),
                "pedidos_novos": val(pedidos),
            }
    return await asyncio.to_thread(_run)
```

- [ ] **Commit**

```bash
git add api.py
git commit -m "feat: add /api/v2/ endpoints for marcas, produtos, listagens, pedidos"
```

---

## Task 5: Deploy e verificação

- [ ] **Push para Render**

```bash
git push origin main
```

- [ ] **Após deploy, executar migração CogniVita**

```bash
curl -X POST https://apostilas-rx0k.onrender.com/api/admin/migrar-cognivita \
  -H "Authorization: Bearer elite200"
# Esperado: {"ok": true}
```

- [ ] **Verificar dados migrados**

```bash
curl https://apostilas-rx0k.onrender.com/api/v2/marcas \
  -H "Authorization: Bearer elite200"
# Esperado: [{"id":1,"nome":"CogniVita","slug":"cognivita",...}]

curl "https://apostilas-rx0k.onrender.com/api/v2/produtos?marca_id=1" \
  -H "Authorization: Bearer elite200"
# Esperado: lista de produtos migrados das apostilas

curl "https://apostilas-rx0k.onrender.com/api/v2/stats" \
  -H "Authorization: Bearer elite200"
# Esperado: {"marcas":1,"produtos":N,"listagens_publicadas":N,"pedidos_novos":0}
```

- [ ] **Verificar tabelas antigas intactas**

```bash
curl https://apostilas-rx0k.onrender.com/api/admin/ml-problemas \
  -H "Authorization: Bearer elite200"
# Esperado: resposta normal — tabelas legadas funcionando em paralelo
```

- [ ] **Commit final se algum ajuste foi necessário**

```bash
git add -p
git commit -m "fix: migration adjustments after production verification"
```

---

## Próximo passo

Com a Fase 1 concluída, o sistema tem o novo schema populado com dados CogniVita e APIs v2 funcionando. A **Fase 2** (Plano `2026-06-05-multi-marca-02-adaptadores.md`) refatora ML e Shopee para a interface `PlataformaAdapter` e usa `contas_plataforma` como fonte de credenciais.
