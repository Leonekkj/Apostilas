# Spec: Kits Automáticos + Imagens com Múltiplos Livros

**Data:** 2026-05-30  
**Status:** Aprovado

---

## Visão Geral

Duas features relacionadas:
1. Imagens de kit mostram N livros (um por apostila) com títulos específicos visíveis
2. Gerador automático de kits combina produtos de tópicos diferentes e cria anúncios

---

## Feature 1 — Imagem do Kit com Múltiplos Livros

### Problema atual
`gerar_capas_kit` usa os mesmos prompts de apostila individual — mostra só 1 livro na capa, sem distinguir os tópicos do kit.

### Solução
Nova função `_build_kit_ai_prompts(apostilas_info, num_exercicios)` em `generator/images.py`.

**Assinatura:**
```python
def _build_kit_ai_prompts(
    apostilas_info: list[dict],  # [{nome, serie_romano}, ...]
    num_exercicios: int,
) -> dict:  # {1: prompt_v1, 2: prompt_v2, 3: prompt_v3}
```

**Layout por quantidade de livros:**
- 2 livros: lado a lado, capas viradas para câmera, ângulo levemente diferente entre eles
- 3 livros: em leque aberto, livro central levemente à frente
- 4 livros: dois na frente, dois atrás levemente elevados formando profundidade

**Cada livro** no prompt descreve explicitamente seu título:
```
"First book cover: title 'MEMÓRIA I' in large dark green bold letters"
"Second book cover: title 'COORDENAÇÃO MOTORA I' in large dark green bold letters"
```

**Variações:**
- V1: product shot — N livros em superfície (com ambiente aleatório do pool)
- V2: lifestyle — idosa à mesa, N livros visíveis ao lado
- V3: flat lay — N livros abertos + fechados vistos de cima

**Integração:** `gerar_capas_kit` passa a chamar `_build_kit_ai_prompts` em vez de `_build_ai_prompts`.

---

## Feature 2 — Geração Automática de Kits

### Lógica de combinação

```
produtos_por_topico = {topico_id: [produto1, produto2, ...]}
para cada combinação de 2, 3, 4 tópicos diferentes:
  para cada tamanho em [30, 60, 90, 120, 150, 200]:
    apostilas = [apostila do topico X com num_ex=tamanho, ...]
    se todas existem e kit não existe ainda:
      criar kit
```

**Regras:**
- Apenas apostilas de **tópicos diferentes** (nunca dois do mesmo tópico)
- Pega a apostila mais recente de cada tópico para o tamanho dado
- Máximo 4 apostilas por kit
- Evita duplicatas: compara `sorted(apostila_ids)` com kits existentes

### Preço
```python
preco_kit = round(sum(preco_individual) * 0.90, 2)
```
Preço individual de cada apostila = `_PRECOS_PRODUTO[num_exercicios]`.

### Nome do kit
Gerado via `content.sugerir_nome_kit(apostilas)` — mesmo mecanismo dos kits manuais.

### Onde roda
Nova função `gerar_kits_automaticos()` em `scheduler.py`, agendada às **6h diariamente**.

Fluxo interno:
1. `database.listar_apostilas_por_topico_e_num_ex()` — nova query no DB
2. `itertools.combinations(topicos, r)` para r in [2, 3, 4]
3. Para cada combinação × tamanho: verifica duplicata → cria kit
4. Kit criado via lógica equivalente ao `POST /api/kit` (sem HTTP, chamada direta às funções)

### Nova função no database.py
```python
def listar_apostilas_por_topico_e_num_ex() -> dict[int, dict[int, int]]:
    """Retorna {topico_id: {num_exercicios: apostila_id}} com apostila mais recente por (topico, tamanho)."""
```

### Nova função no database.py
```python
def kit_existe(apostila_ids: list[int]) -> bool:
    """Verifica se já existe kit com exatamente esse conjunto de apostila_ids."""
```

---

## Arquivos Afetados

| Arquivo | Mudança |
|---------|---------|
| `generator/images.py` | + `_build_kit_ai_prompts()`, atualiza `gerar_capas_kit` |
| `scheduler.py` | + `gerar_kits_automaticos()`, job às 6h |
| `database.py` | + `listar_apostilas_por_topico_e_num_ex()`, + `kit_existe()` |

---

## Escala Estimada

Com 6 tópicos completos (todos tamanhos disponíveis):
- C(6,2) × 6 = 90 kits de 2 tópicos
- C(6,3) × 6 = 120 kits de 3 tópicos  
- C(6,4) × 6 = 90 kits de 4 tópicos
- **Total: até 300 kits**

Na prática menos, pois nem todo tópico terá todas as séries/tamanhos disponíveis. O job é idempotente — kits já existentes são ignorados.
