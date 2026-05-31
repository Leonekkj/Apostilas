# Spec: Caça-Palavras e Temáticos — Linha 5 e 13

**Data:** 2026-05-31
**Status:** Aprovado

## Contexto

O sistema já gera e publica apostilas cognitivas para idosos no Mercado Livre. Esta spec adiciona uma nova categoria de produto — caça-palavras — em volumes por dificuldade e por tema. A escolha foi baseada em demanda de busca no ML e viabilidade técnica com o sistema atual.

## Catálogo de Produtos

### Volumes por dificuldade (genéricos)

| Produto | Grade | Palavras/puzzle | Direções | Puzzles |
|---|---|---|---|---|
| Caça-Palavras Fácil | 12×12 | 8 | Horizontal + Vertical | 60 |
| Caça-Palavras Médio | 15×15 | 12 | H + V + diagonal ↘ | 60 |
| Caça-Palavras Difícil | 18×18 | 18 | Todas (inclui reverso) | 60 |
| Caça-Palavras Gigante | Misto | Misto | Misto | 300 |

### Volumes temáticos (60 puzzles cada)

| Tema | Slug |
|---|---|
| Futebol | futebol |
| Culinária | culinaria |
| Animais | animais |
| Brasil | brasil |
| Música | musica |
| Natureza | natureza |

Cada tema pode ter versão Fácil, Médio ou Difícil. O Gigante temático combina todos os níveis do tema.

## Modelo de Dados

### Campos novos na tabela `produtos`

```sql
ALTER TABLE produtos ADD COLUMN nome TEXT;
ALTER TABLE produtos ADD COLUMN tema TEXT;        -- NULL = genérico
ALTER TABLE produtos ADD COLUMN dificuldade TEXT; -- facil | medio | dificil | gigante | NULL
```

Migration idempotente via `_add_columns` já existente em `database.py`.

### Novo tópico

Inserido via seed em `database.py`:

```python
{"nome": "Caça-Palavras", "slug": "caca-palavras", "keywords": "caça palavras idosos passatempo letras"}
```

### Listas de palavras

Arquivos JSON em `content/palavras/{tema}.json`. Estrutura:

```json
{
  "tema": "futebol",
  "palavras": ["GOL", "ÁRBITRO", "CAMPO", "CHUTEIRA", "PLACAR", "GOLEIRO", "TORCIDA", ...]
}
```

Pool mínimo por arquivo: 150 palavras (garante 300 puzzles sem repetição em um Gigante). Palavras em maiúsculo, sem acento, máx. 12 caracteres para caber no grid fácil.

## Geração de Conteúdo

### Módulo: `gerar_caca_palavras.py`

Função principal:

```python
def gerar_caca_palavras(tema: str, dificuldade: str, num_puzzles: int) -> list[dict]:
    """
    Retorna lista de puzzles. Cada puzzle é um dict com:
      grid: list[list[str]]       — grade preenchida
      palavras: list[str]         — palavras escondidas
      gabarito: list[list[str]]   — grade com posições marcadas
    """
```

### Algoritmo de backtracking

Para cada palavra:
1. Escolhe direção aleatória (restrita pela dificuldade)
2. Escolhe posição inicial aleatória na grade
3. Verifica se cabe sem conflito de letras (conflito só é permitido se a letra coincide)
4. Se não cabe após N tentativas, descarta a palavra e usa outra do pool
5. Preenche células vazias com letras aleatórias (vogais com peso maior — mais legível para idosos)

Sem biblioteca externa — implementação própria com `random`. Simples o suficiente para este caso de uso.

### Integração com o pipeline atual

O gerador é chamado no mesmo ponto onde os outros geradores são chamados. Retorna `conteudo_json` com os puzzles, que é salvo na `apostila` e depois renderizado em PDF pela camada de layout.

## Layout do PDF

### Página de puzzle

```
┌─────────────────────────────────────┐
│  [Logo CogniVita]    Puzzle #12     │
│  Caça-Palavras de Futebol — Médio   │
├─────────────────────────────────────┤
│                                     │
│   G O L A R B I T R O C H U T      │
│   E S A M P O F U T E B O L A      │
│   ... (grid 15×15) ...              │
│                                     │
├─────────────────────────────────────┤
│  Encontre as palavras:              │
│  GOL  ÁRBITRO  CAMPO  CHUTEIRA      │
│  PLACAR  GOLEIRO  TORCIDA           │
└─────────────────────────────────────┘
```

- 1 puzzle por página
- Fonte mínima 14pt (acessibilidade para idosos)
- Alto contraste: fundo branco, letras pretas, grid com bordas definidas
- Letras do grid espaçadas (não coladas)

### Gabarito

Incluído nas últimas páginas do PDF. Mesmo grid com as palavras encontradas destacadas em cinza. 4 gabaritos por página (tamanho reduzido).

### Capa

Gerada automaticamente com nome do produto e tema. Segue padrão visual dos outros produtos. Ícone do tema em SVG simples (bola, panela, pata, bandeira, nota musical, folha).

## Fluxo de Publicação

Idêntico ao fluxo atual — nenhuma mudança no dashboard ou na API:

1. Criar produto no dashboard (tópico = Caça-Palavras, nome, tema, dificuldade, num_puzzles)
2. Gerar PDF automaticamente
3. Criar anúncio vinculado ao produto
4. Publicar no ML pelo botão existente

## O que NÃO muda

- Dashboard (app/index.html) — nenhuma alteração de UI
- API de publicação no ML — nenhuma alteração
- Tabelas `apostilas`, `anuncios`, `vendas` — nenhuma alteração
- Entrega automática por mensagem ML — funciona para caça-palavras sem alteração

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `database.py` | Migration: colunas `nome`, `tema`, `dificuldade` em `produtos`; seed tópico `caca-palavras` |
| `gerar_caca_palavras.py` | Novo módulo na raiz: backtracking + preenchimento + renderização ReportLab |
| `_renderer_premium.py` | Adicionar função de renderização de grid de caça-palavras (reutiliza estilos existentes) |
| `content/palavras/*.json` | 6 arquivos de palavras por tema + 1 genérico (novo diretório) |
| `api.py` | Endpoint de criação de produto passa `nome`/`tema`/`dificuldade` ao salvar |
