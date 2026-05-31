"""
gerar_caca_palavras.py
Gera puzzles de caça-palavras e PDF via ReportLab.
"""
import json
import random
import unicodedata
from pathlib import Path

# ──────────────────────────────────────────────────────
# Configurações por dificuldade
# ──────────────────────────────────────────────────────
CONFIGS = {
    "facil":   {"tamanho": 12, "num_palavras": 8,  "direcoes": ["H", "V"]},
    "medio":   {"tamanho": 15, "num_palavras": 12, "direcoes": ["H", "V", "D"]},
    "dificil": {"tamanho": 18, "num_palavras": 18, "direcoes": ["H", "V", "D", "HR", "VR", "DR"]},
    "gigante": {"tamanho": 15, "num_palavras": 12, "direcoes": ["H", "V", "D"]},
}

VOGAIS = "AEIOU"
CONSOANTES = "BCDFGHJKLMNPQRSTVWXYZ"
# Preenche vazios com mais vogais para facilitar leitura dos idosos
_FILL_POOL = VOGAIS * 3 + CONSOANTES


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def carregar_palavras(tema: str) -> list[str]:
    """Carrega palavras de content/palavras/{tema}.json, filtrando >12 chars."""
    base = Path(__file__).parent / "content" / "palavras"
    arquivo = base / f"{tema}.json"
    if not arquivo.exists():
        arquivo = base / "geral.json"
    data = json.loads(arquivo.read_text(encoding="utf-8"))
    return [_sem_acento(p.strip().upper()) for p in data["palavras"] if 3 <= len(p.strip()) <= 12]


# ──────────────────────────────────────────────────────
# Direções: (delta_row, delta_col)
# ──────────────────────────────────────────────────────
_DELTA = {
    "H":  (0,  1),   # →
    "HR": (0, -1),   # ←
    "V":  (1,  0),   # ↓
    "VR": (-1, 0),   # ↑
    "D":  (1,  1),   # ↘
    "DR": (1, -1),   # ↙
}


def _cabe(grid: list[list[str]], palavra: str, row: int, col: int, dr: int, dc: int) -> bool:
    """Retorna True se a palavra cabe na posição sem conflito de letras."""
    n = len(grid)
    for i, letra in enumerate(palavra):
        r, c = row + i * dr, col + i * dc
        if not (0 <= r < n and 0 <= c < n):
            return False
        if grid[r][c] not in ("", letra):
            return False
    return True


def _encaixar(grid: list[list[str]], gabarito: list[list[str]], palavra: str, row: int, col: int, dr: int, dc: int) -> None:
    """Escreve a palavra no grid e marca no gabarito."""
    for i, letra in enumerate(palavra):
        r, c = row + i * dr, col + i * dc
        grid[r][c] = letra
        gabarito[r][c] = letra


def _preencher_vazios(grid: list[list[str]]) -> None:
    """Preenche células vazias com letras aleatórias."""
    for row in grid:
        for i, cell in enumerate(row):
            if cell == "":
                row[i] = random.choice(_FILL_POOL)


def gerar_puzzles(tema: str, dificuldade: str, num_puzzles: int) -> list[dict]:
    """
    Gera lista de puzzles de caça-palavras.

    Returns:
        list de dicts com chaves: grid, palavras, gabarito
        - grid: list[list[str]]     — grade preenchida com letras
        - palavras: list[str]       — palavras escondidas no grid
        - gabarito: list[list[str]] — grid com só as palavras (vazios como '.')
    """
    cfg = CONFIGS.get(dificuldade, CONFIGS["medio"])
    tamanho = cfg["tamanho"]
    num_palavras = cfg["num_palavras"]
    direcoes = cfg["direcoes"]

    pool = carregar_palavras(tema)
    # Filtra palavras que cabem no grid
    pool = [p for p in pool if len(p) <= tamanho]
    random.shuffle(pool)

    puzzles = []
    usadas_global: set[str] = set()

    for _ in range(num_puzzles):
        grid = [[""] * tamanho for _ in range(tamanho)]
        gabarito = [["."] * tamanho for _ in range(tamanho)]
        palavras_encaixadas: list[str] = []

        # Pool local: evita repetir palavra no mesmo volume (até esgotar)
        disponiveis = [p for p in pool if p not in usadas_global]
        if len(disponiveis) < num_palavras:
            usadas_global.clear()
            disponiveis = pool[:]
        random.shuffle(disponiveis)

        for palavra in disponiveis:
            if len(palavras_encaixadas) >= num_palavras:
                break
            dr, dc = _DELTA[random.choice(direcoes)]
            encaixou = False
            for _ in range(100):  # 100 tentativas por palavra
                row = random.randint(0, tamanho - 1)
                col = random.randint(0, tamanho - 1)
                if _cabe(grid, palavra, row, col, dr, dc):
                    _encaixar(grid, gabarito, palavra, row, col, dr, dc)
                    palavras_encaixadas.append(palavra)
                    usadas_global.add(palavra)
                    encaixou = True
                    break

        _preencher_vazios(grid)
        puzzles.append({
            "grid":     grid,
            "palavras": palavras_encaixadas,
            "gabarito": gabarito,
        })

    return puzzles
