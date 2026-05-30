# Kit Automático + Imagens com Múltiplos Livros — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gerar imagens de kit mostrando N livros com títulos específicos e criar kits automaticamente combinando apostilas de tópicos diferentes.

**Architecture:** (1) `_build_kit_ai_prompts` gera prompts com N livros descritos individualmente; `gerar_capas_kit` passa a usá-la. (2) Duas funções DB auxiliares suportam deduplicação e lookup. (3) `gerar_kits_automaticos` no scheduler combina tópicos via `itertools.combinations` e cria kits faltantes às 6h diariamente.

**Tech Stack:** Python asyncio, Pillow, Wan AI API (DashScope), SQLite/PostgreSQL, APScheduler

---

### Task 1: database.py — funções auxiliares para kits automáticos

**Files:**
- Modify: `database.py` (após `criar_kit`, linha ~419)

- [ ] **Step 1: Adicionar `listar_apostilas_por_topico_e_num_ex`**

Inserir após a função `criar_kit`:

```python
def listar_apostilas_por_topico_e_num_ex() -> dict:
    """Retorna {topico_id: {num_exercicios: apostila_id}} — apostila mais recente por (topico, tamanho)."""
    conn = _get_conn()
    try:
        cur = conn.execute("""
            SELECT topico_id, num_exercicios, MAX(id) AS apostila_id
            FROM apostilas
            WHERE produto_id IS NOT NULL
            GROUP BY topico_id, num_exercicios
        """)
        result: dict = {}
        for row in cur.fetchall():
            t, n, a = row["topico_id"], row["num_exercicios"], row["apostila_id"]
            result.setdefault(t, {})[n] = a
        return result
    finally:
        conn.close()
```

- [ ] **Step 2: Adicionar `kit_existe`**

Inserir logo após a função anterior:

```python
def kit_existe(apostila_ids: list) -> bool:
    """Retorna True se já existe kit com exatamente esse conjunto de apostila_ids."""
    target = sorted(int(x) for x in apostila_ids)
    conn = _get_conn()
    try:
        cur = conn.execute("SELECT apostila_ids FROM kits")
        for row in cur.fetchall():
            existing = sorted(int(x) for x in json.loads(row["apostila_ids"] or "[]"))
            if existing == target:
                return True
        return False
    finally:
        conn.close()
```

- [ ] **Step 3: Verificar manualmente**

```python
# python -c "
import database
m = database.listar_apostilas_por_topico_e_num_ex()
print('Tópicos:', list(m.keys()))
print('Apostilas topico 1:', m.get(1))
print('kit_existe([]):', database.kit_existe([]))
# "
```

Esperado: dict com topico_ids e num_ex mapeados para apostila_id, `kit_existe` retorna False para lista vazia.

- [ ] **Step 4: Commit**

```bash
git add database.py
git commit -m "feat: add listar_apostilas_por_topico_e_num_ex e kit_existe para kits automáticos"
```

---

### Task 2: generator/images.py — `_build_kit_ai_prompts` e `gerar_capas_kit`

**Files:**
- Modify: `generator/images.py`

- [ ] **Step 1: Adicionar `_build_kit_ai_prompts` antes de `gerar_capas_kit` (linha ~1449)**

```python
def _build_kit_ai_prompts(apostilas_info: list[dict], num_exercicios: int) -> dict:
    """Gera prompts para capa de kit com N livros, cada um com seu título específico.

    apostilas_info: lista de dicts com chave 'nome' (topico_nome de cada apostila).
    """
    import random
    n = len(apostilas_info)
    ex = f"{num_exercicios} EXERCICIOS"
    ambiente_v1 = random.choice(_AMBIENTES_V1)
    ambiente_v2 = random.choice(_AMBIENTES_V2)
    ambiente_v3 = random.choice(_AMBIENTES_V3)

    # Descreve cada livro individualmente com seu título
    posicoes = ["First", "Second", "Third", "Fourth"]
    def _book_desc(i: int, nome: str) -> str:
        titulo = nome.upper()
        return (
            f"{posicoes[i]} book cover: warm cream background with dark forest green watercolor shapes, "
            f"brand COGNIVITA in small bold dark green at top, "
            f"large bold title \"{titulo}\" centered in dark forest green, "
            f"badge \"{ex}\" at bottom, gold spiral binding on left."
        )

    books_desc = " ".join(_book_desc(i, a["nome"]) for i, a in enumerate(apostilas_info))

    # Arranjo espacial por quantidade de livros
    if n == 2:
        arrangement_v1 = "two thick spiral-bound workbooks standing upright side by side, covers facing the camera, slight angle between them"
        arrangement_v2 = "two closed spiral-bound workbooks standing beside her, both covers visible and sharp"
        arrangement_v3 = "two spiral-bound workbooks propped upright side by side, both covers fully visible"
    elif n == 3:
        arrangement_v1 = "three spiral-bound workbooks in a slight fan formation, center book slightly forward, all covers visible"
        arrangement_v2 = "three closed spiral-bound workbooks arranged in a fan beside her, all covers facing the camera"
        arrangement_v3 = "three spiral-bound workbooks in a slight fan arrangement, all covers fully visible"
    else:  # 4
        arrangement_v1 = "four spiral-bound workbooks arranged with two in front and two slightly elevated behind, all covers visible"
        arrangement_v2 = "four closed spiral-bound workbooks arranged in a 2x2 formation beside her, all covers visible"
        arrangement_v3 = "four spiral-bound workbooks in a 2x2 grid arrangement, all covers fully visible"

    badge_kit = f"KIT {n} EM 1 · {ex}"

    return {
        1: (
            f"Ultra professional e-commerce product photography, photorealistic 4k, organic warm editorial style. "
            f"Hero: {arrangement_v1} on a {ambiente_v1}. "
            f"{books_desc} "
            f"Soft diffused natural studio light, premium editorial mood, ultra sharp detail on all covers."
        ),
        2: (
            f"Warm authentic lifestyle photo for Brazilian e-commerce, photorealistic 4k, natural light. "
            f"Elderly Brazilian woman 70s, short white curly hair, reading glasses, soft cardigan, "
            f"{ambiente_v2}, smiling warmly, writing in an open workbook. "
            f"{arrangement_v2}. "
            f"{books_desc} "
            f"Authentic heartwarming expression, shallow depth of field, cinematic warm mood."
        ),
        3: (
            f"Professional overhead flat lay photography for Brazilian e-commerce, photorealistic 4k, warm organic aesthetic. "
            f"{arrangement_v3} on {ambiente_v3} "
            f"{books_desc} "
            f"Soft diffused natural light from above, no harsh shadows, clean airy composition, ultra sharp detail."
        ),
    }
```

- [ ] **Step 2: Atualizar `gerar_capas_kit` para usar `_build_kit_ai_prompts`**

Localizar `gerar_capas_kit` (~linha 1449+) e substituir a linha:
```python
    prompts = _build_ai_prompts(kit_nome, total_exercicios)
```
por:
```python
    apostilas_info = [{"nome": a.get("topico_nome", a.get("nome", kit_nome))} for a in apostilas]
    prompts = _build_kit_ai_prompts(apostilas_info, total_exercicios)
```

- [ ] **Step 3: Verificar imports e sintaxe**

```bash
python -c "from generator import images; print('OK')"
```

Esperado: `OK` sem erros.

- [ ] **Step 4: Teste rápido com mock**

```python
# python -c "
from generator.images import _build_kit_ai_prompts
info = [{'nome': 'Memoria'}, {'nome': 'Coordenacao Motora'}]
p = _build_kit_ai_prompts(info, 60)
assert 'MEMORIA' in p[1] and 'COORDENACAO MOTORA' in p[1]
assert 'two thick spiral-bound' in p[1]
print('2 livros OK')

info3 = [{'nome': 'Memoria'}, {'nome': 'Coordenacao Motora'}, {'nome': 'Atencao'}]
p3 = _build_kit_ai_prompts(info3, 60)
assert 'three spiral-bound' in p3[1]
print('3 livros OK')
# "
```

- [ ] **Step 5: Commit**

```bash
git add generator/images.py
git commit -m "feat: _build_kit_ai_prompts mostra N livros com títulos específicos na capa do kit"
```

---

### Task 3: scheduler.py — `gerar_kits_automaticos`

**Files:**
- Modify: `scheduler.py`

- [ ] **Step 1: Adicionar imports no topo de `scheduler.py`**

```python
import itertools
```

Adicionar junto aos imports existentes (após `import time`).

- [ ] **Step 2: Adicionar constantes de preço (copiar de api.py)**

Adicionar após as constantes existentes (`PAUSE_BETWEEN`):

```python
_FATIAS = [30, 60, 90, 120, 150, 200]
_PRECOS_PRODUTO = {30: 14.90, 60: 19.90, 90: 24.90, 120: 29.90, 150: 34.90, 200: 44.90}
```

- [ ] **Step 3: Adicionar função `gerar_kits_automaticos`**

Inserir antes da função `main()`:

```python
def gerar_kits_automaticos():
    """Gera kits combinando apostilas de tópicos diferentes (2, 3 e 4 por kit).
    
    Idempotente: kits já existentes são ignorados.
    Roda diariamente às 6h.
    """
    from generator import content as gen_content
    from generator import images as gen_images

    mapa = database.listar_apostilas_por_topico_e_num_ex()
    topicos = list(mapa.keys())

    if len(topicos) < 2:
        logger.info("Kits automáticos: menos de 2 tópicos disponíveis, pulando.")
        return

    logger.info("Kits automáticos: %d tópicos, gerando combinações 2-4", len(topicos))
    kits_criados = 0
    kits_pulados = 0

    for r in [2, 3, 4]:
        if len(topicos) < r:
            continue
        for combo_topicos in itertools.combinations(topicos, r):
            for num_ex in _FATIAS:
                # Verifica se todas as apostilas existem para esse tamanho
                apostila_ids = []
                for topico_id in combo_topicos:
                    aid = mapa.get(topico_id, {}).get(num_ex)
                    if aid is None:
                        break
                    apostila_ids.append(aid)

                if len(apostila_ids) != r:
                    kits_pulados += 1
                    continue

                # Evita duplicatas
                if database.kit_existe(apostila_ids):
                    kits_pulados += 1
                    continue

                try:
                    apostilas_objs = [database.buscar_apostila_por_id(aid) for aid in apostila_ids]
                    nome = gen_content.sugerir_nome_kit(apostilas_objs)
                    kit_id = database.criar_kit(nome, apostila_ids)

                    # Preço: soma individual com 10% de desconto
                    preco_individual = _PRECOS_PRODUTO.get(num_ex, 29.90)
                    preco_kit = round(preco_individual * r * 0.90, 2)

                    total_exercicios = num_ex * r
                    titulos = gen_content.gerar_titulos_kit_ml(nome, apostilas_objs, total_exercicios)
                    topico_kit = {"nome": nome}
                    descricao = gen_content.gerar_descricao_ml(topico_kit, total_exercicios)

                    for i, title in enumerate(titulos, start=1):
                        image_paths = gen_images.gerar_capas_kit(kit_id, nome, apostilas_objs, i)
                        image_path = image_paths[0] if image_paths else None

                        anuncio_id = database.criar_anuncio(
                            None, "fisico", i, title["titulo"], preco_kit,
                            i, title.get("angulo", ""), kit_id, descricao,
                        )
                        if image_path:
                            database.atualizar_anuncio(anuncio_id, imagem_path=image_path)

                    kits_criados += 1
                    logger.info("Kit criado: %s (%d ex, %d apostilas, R$%.2f)", nome, num_ex, r, preco_kit)

                except Exception as e:
                    logger.error("Erro ao criar kit automático (%s, %d ex): %s", combo_topicos, num_ex, e)

    logger.info("Kits automáticos concluído: %d criados, %d pulados", kits_criados, kits_pulados)
```

- [ ] **Step 4: Registrar job às 6h no scheduler**

Localizar o bloco de `scheduler.add_job` dentro de `main()` e adicionar:

```python
    scheduler.add_job(gerar_kits_automaticos, "cron", hour=6, minute=0)
```

Ficará junto com os outros jobs existentes.

- [ ] **Step 5: Verificar sintaxe**

```bash
python -c "import scheduler; print('OK')"
```

Esperado: `OK`.

- [ ] **Step 6: Teste com --once em dry-run (sem publicar)**

```bash
python -c "
import database, scheduler
# Verifica que a função existe e aceita ser chamada com DB vazio de kits auto
print('gerar_kits_automaticos:', callable(scheduler.gerar_kits_automaticos))
"
```

Esperado: `gerar_kits_automaticos: True`.

- [ ] **Step 7: Commit**

```bash
git add scheduler.py
git commit -m "feat: gerar_kits_automaticos — combinações 2-4 tópicos, 10% desconto, job às 6h"
```
