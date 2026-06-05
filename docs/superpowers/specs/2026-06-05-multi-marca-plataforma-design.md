# Design: Sistema Multi-Marca e Multi-Plataforma

**Data:** 2026-06-05  
**Status:** Aprovado

## Contexto

O sistema atual (CogniVita) é uma plataforma de venda de apostilas cognitivas no Mercado Livre, com lógica de marca, tabelas e geração de conteúdo hardcoded para esse nicho específico. O objetivo é evoluir para uma plataforma de gestão de vendas multi-marca, multi-produto e multi-plataforma, operada pelo próprio dono (não SaaS).

Modelo de negócio: print-on-demand. Conteúdo criado pelo operador, gráfica parceira imprime e envia ao cliente após a venda.

---

## Modelo de Dados

### Novas tabelas

```sql
marcas
  id          SERIAL PK
  nome        TEXT NOT NULL
  slug        TEXT UNIQUE NOT NULL
  cor_principal TEXT
  logo_url    TEXT
  ativo       BOOLEAN DEFAULT true
  criado_em   TIMESTAMP

contas_plataforma
  id          SERIAL PK
  marca_id    INTEGER FK marcas
  plataforma  TEXT NOT NULL  -- 'ml' | 'shopee' | 'amazon'
  credenciais JSONB          -- tokens, client_id/secret (não mais em env vars)
  ativo       BOOLEAN DEFAULT true
  criado_em   TIMESTAMP

produtos
  id              SERIAL PK
  marca_id        INTEGER FK marcas
  nome            TEXT NOT NULL
  descricao       TEXT
  tipo            TEXT NOT NULL  -- 'proprio' | 'revenda'
  preco_base      NUMERIC(10,2)
  custo_producao  NUMERIC(10,2)
  imagem_url      TEXT           -- R2
  conteudo_path   TEXT           -- caminho/referência ao conteúdo (exercícios, etc.)
  ativo           BOOLEAN DEFAULT true
  criado_em       TIMESTAMP

listagens
  id                  SERIAL PK
  produto_id          INTEGER FK produtos
  conta_id            INTEGER FK contas_plataforma
  titulo              TEXT NOT NULL
  preco               NUMERIC(10,2)
  status              TEXT DEFAULT 'rascunho'  -- rascunho | publicado | pausado | arquivado | deletado
  plataforma_item_id  TEXT                     -- ml_id, shopee_item_id, amazon_asin
  imagem_url          TEXT                     -- R2
  erro_msg            TEXT
  criado_em           TIMESTAMP
  atualizado_em       TIMESTAMP

pedidos
  id                    SERIAL PK
  listagem_id           INTEGER FK listagens
  plataforma_pedido_id  TEXT NOT NULL
  status                TEXT DEFAULT 'novo'    -- novo | pdf_gerado | enviado_grafica | entregue | cancelado
  valor                 NUMERIC(10,2)
  nome_cliente          TEXT
  endereco_entrega      JSONB
  pdf_gerado            BOOLEAN DEFAULT false
  enviado_grafica       BOOLEAN DEFAULT false
  criado_em             TIMESTAMP
  atualizado_em         TIMESTAMP
```

### Migração CogniVita

Script único que:
1. Cria marca `cognivita` com slug `cognivita`
2. Migra credenciais ML do env var para `contas_plataforma`
3. Converte cada `apostila`/`kit` em `produto`
4. Converte cada `anuncio` em `listagem` com `conta_id` da conta ML CogniVita
5. Tabelas antigas (`apostilas`, `kits`, `anuncios`, `topicos`) são mantidas como legado até validação completa

---

## Adaptadores de Plataforma

Interface comum em `platforms/base.py`:

```python
class PlataformaAdapter:
    def publicar(listagem: dict, produto: dict, credenciais: dict) -> str
        # Retorna plataforma_item_id

    def atualizar(plataforma_item_id: str, dados: dict, credenciais: dict) -> bool

    def sincronizar_status(conta: dict) -> list[dict]
        # Retorna [{plataforma_item_id, status, sub_status}]

    def buscar_pedidos(conta: dict) -> list[dict]
        # Retorna pedidos novos desde última sincronização
```

Implementações:
- `platforms/ml/adapter.py` — refatora `ml/client.py` atual
- `platforms/shopee/adapter.py` — refatora `shopee/client.py` atual
- `platforms/amazon/adapter.py` — implementação futura

Credenciais saem de env vars e passam a ser lidas de `contas_plataforma.credenciais`. Múltiplas contas da mesma plataforma são suportadas naturalmente.

---

## Geração de Conteúdo

### Capas (imagens)

`generator/images.py` torna-se genérico:
- Template de capa configurado por marca (paleta, logo, estilo)
- Suporta geração via FAL AI (opcional) e Pillow (fallback)
- Upload automático para R2 após geração

### PDF (sob demanda)

`generator/pdf.py` é invocado somente após a venda:
- Recebe `produto.conteudo_path` + dados do pedido
- Gera PDF finalizado
- Faz upload para R2 e atualiza `pedidos.pdf_gerado = true`

### Envio para gráfica

`fulfillment/grafica.py`:
- Recebe PDF URL (R2) + endereço do pedido
- Envia para API da gráfica parceira (Printi ou Graka)
- Atualiza `pedidos.enviado_grafica = true`

---

## Pipeline Completo

### Criação de produto
```
1. Operador define produto no dashboard (nome, descrição, conteúdo, preço)
2. Sistema gera capa via template da marca → upload R2
3. Operador aprova imagem
4. Operador seleciona contas/plataformas para publicar
5. Sistema chama adapter.publicar() para cada conta selecionada
6. Listagens criadas no banco com plataforma_item_id
```

### Fulfillment (pós-venda)
```
1. Job noturno: adapter.buscar_pedidos() para todas as contas ativas
2. Novos pedidos salvos em `pedidos`
3. Para cada pedido novo: generator/pdf.py gera PDF
4. fulfillment/grafica.py envia para gráfica com endereço do cliente
5. Gráfica imprime e envia diretamente ao cliente
```

---

## Jobs Automáticos (APScheduler)

| Job | Horário | Ação |
|---|---|---|
| `sincronizar_status` | 06:00 | Atualiza status de todas as listagens |
| `buscar_pedidos` | A cada 2h | Puxa pedidos novos de todas as plataformas |
| `processar_pedidos` | A cada 2h | Gera PDF + envia gráfica para pedidos novos |

---

## Dashboard

```
/                   → Resumo geral (vendas, pedidos pendentes, listagens com problema)
/marcas             → CRUD de marcas
/marcas/:id/contas  → Credenciais por plataforma para a marca
/produtos           → Catálogo de produtos (filtro por marca)
/produtos/novo      → Criar produto + gerar capa
/listagens          → Status por produto/plataforma
/pedidos            → Pedidos recebidos, status fulfillment
/configuracoes      → Gráfica parceira, templates de capa por marca
```

---

## Estrutura de Arquivos

```
api.py                      ← FastAPI refatorado (sem lógica CogniVita)
database.py                 ← Novo schema multi-marca
storage.py                  ← R2 (sem mudança)
platforms/
  base.py                   ← Interface PlataformaAdapter
  ml/adapter.py             ← Refatora ml/client.py
  shopee/adapter.py         ← Refatora shopee/client.py
  amazon/adapter.py         ← Futuro
generator/
  images.py                 ← Genérico, template por marca
  pdf.py                    ← Geração sob demanda
fulfillment/
  grafica.py                ← Integração Printi/Graka
migrations/
  001_multi_marca.sql       ← Cria novas tabelas
  002_migrar_cognivita.py   ← Script de migração dos dados atuais
app/index.html              ← Dashboard refatorado
```

---

## O que NÃO muda

- Render como plataforma de deploy
- PostgreSQL no Railway/Render
- R2 para armazenamento de imagens
- Autenticação via ADMIN_TOKEN (por ora)

---

## Fora de escopo (por ora)

- Amazon (adaptador deixado como placeholder)
- Multi-usuário / SaaS
- Integração com ERP ou contabilidade
- Relatórios financeiros avançados
