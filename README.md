
# Bit Packing Compression — Software Engineering Project 2025

Ce dépôt contient une implémentation Python de **bit packing** pour compresser des tableaux d’entiers avec :

- Deux modes de base
  - **CrossBoundaryPacker** — autorise les valeurs à traverser les frontières des mots 32 bits
  - **NoCrossPacker** — interdit le chevauchement ; chaque mot 32 bits contient `floor(32/k)` valeurs
- Des variantes **avec zone d’overflow** qui stockent les outliers séparément tout en préservant l’accès aléatoire O(1) :
  - **OverflowBitPacker(base="cross"|"nocross")**
- **Accès direct** : `get(i)` retourne l’i-ème entier original sans décompresser tout le flux
- **Support des signés** :
  - **ZigZag** (recommandé) ou **complément à deux** (two’s complement)
- **Benchmarks** et un CLI pour calculer le **seuil de rentabilité (break‑even)** où la compression devient bénéfique selon la latence et le débit

---

## Sommaire

- [Installation](#installation)
- [Utilisation rapide (CLI)](#utilisation-rapide-cli)
- [API (Python)](#api-python)
- [Spécification Overflow](#spécification-overflow)
- [Protocole de mesure & Break-even](#protocole-de-mesure--break-even)
- [Tests](#tests)
- [Nombres négatifs (bonus)](#nombres-négatifs-bonus)
- [Livrables & Envoi](#livrables--envoi)
- [Crédits](#crédits)

---

## Installation

> Aucune dépendance externe obligatoire pour le cœur du projet.

### Windows (PowerShell)

```powershell
# Dans le dossier du projet
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass  # si nécessaire
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### macOS / Linux (Bash)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
```

---

## Utilisation rapide (CLI)

Le CLI `cli.py` exécute un benchmark, vérifie la correction et calcule le break‑even.

```powershell
# Chevauchement autorisé, valeurs sur ~12 bits
python cli.py --kind cross -n 1000000 --max 4095 --latency 0.05 --bitrate 10000000

# Overflow + cross (utile quand quelques valeurs sont très grandes)
python cli.py --kind overflow-cross -n 1_000_000 --max 4095

# Pas de chevauchement (slots fixes)
python cli.py --kind nocross -n 100000 --max 255
```

Options principales :

- `--kind {cross|nocross|overflow-cross|overflow-nocross}`
- `-n` : taille du tableau
- `--max` : valeur max (détermine la largeur binaire k)
- `--latency` : latence en secondes
- `--bitrate` : débit en bits/s
- `--signed` / `--zigzag` : prise en charge des signés

Sorties : ratio de compression, temps `compress` / `get` / `decompress`, `R*` (débit seuil), et comparaison des temps de transmission compressé vs non compressé.

---

## API (Python)

```python
from bitpacking import PackerFactory

# Créer un packer
packer = PackerFactory.create("cross", signed=False, zigzag=False)

# Compresser
arr = [1, 2, 3, 4095, 4, 5]
packer.compress(arr)

# Accès direct
print(packer.get(3))  # -> 4095

# Décompresser dans un buffer fourni
out = [0] * packer.size()
packer.decompress(out)  # out == arr
```

Types acceptés par la factory :

- `"cross"`
- `"nocross"`
- `"overflow-cross"`
- `"overflow-nocross"`

---

## Spécification Overflow

Idée : si une minorité de valeurs nécessite beaucoup de bits, on les place dans une zone d’overflow ; le flux principal garde des valeurs « petites ».

Choisir `k_small` (bits inline). Seuil : `T = 2^{k_small} - 1`.

- Nombre d’overflow `m` = nb de valeurs `> T`.
- Largeur du flux principal : `B_main = 1 + max(k_small, ceil(log2(m)))`
  - flag (1 bit) : `0` = valeur inline, `1` = index overflow
  - payload (`B_main-1` bits) : valeur (`k_small` bits) ou index `[0..m-1]`
- Zone d’overflow : largeur `k_over = ceil(log2(max_overflow + 1))`
- Bits totaux : `n * B_main + m * k_over` → on balaye plusieurs `k_small` et on choisit celui minimisant ce total.

Exemple : `[1,2,3,1024,4,5,2048]`, `k_small=3`, `m=2`, `B_main=4`.
Flux principal : `0-1, 0-2, 0-3, 1-0, 0-4, 0-5, 1-1`  
Zone overflow : `1024, 2048`.

---

## Protocole de mesure & Break-even

Mesures (dans `cli.py`) :

- Horloge haute résolution : `time.perf_counter_ns()`
- Warmups (stabilisation) puis best‑of :
  - `compress` & `get(i)` : best‑of‑7
  - `decompress` : best‑of‑5 (dans un buffer préalloué)
- Indices aléatoires pour `get(i)` (évite les biais de prédiction de branchements)

Analyse de rentabilité :

- Non compressé : `T0 = t + 32n / R`
- Compressé : `T1 = t + C + D + B_c / R`

Condition de gain : `C + D ≤ (32n − B_c) / R`

Débit seuil (break‑even) :

```
R* = (32n - B_c) / (C + D)
```

Si `R ≤ R*`, compresser est bénéfique.

Le CLI affiche `R*` et compare `T0` vs `T1` pour tes paramètres (`t`, `R`).

---

## Tests

Les tests valident la correction (round‑trip, overflow, signés).

### Windows (PowerShell)

```powershell
.venv\Scripts\Activate.ps1
python -m pip install pytest
python -m pytest -q
```

### macOS / Linux (Bash)

```bash
source .venv/bin/activate
pip install pytest
pytest -q
```

Options utiles :

```bash
pytest -q --durations=5   # top 5 tests les plus lents
pytest -vv                # verbose
pytest -k overflow -vv    # filtrer par mot-clé
```

---

## Nombres négatifs (bonus)

Deux stratégies :

1. **ZigZag** : mappe les entiers signés en non signés (petites magnitudes → petits codes) → meilleure compression quand |x| est souvent petit.
2. **Complément à deux** (two’s complement) : plus simple mais `k` doit couvrir le plus négatif → risque de gaspiller des bits si une seule valeur extrême existe.

Les deux sont supportées via la factory et le CLI (`--zigzag` ou `--signed`).

---

## Livrables & Envoi

- Code Python (sans notebook), factory incluse
- README (ce document) + rapport PDF
- Benchmarks + protocole de mesure
- Dépôt GitHub public recommandé

Date limite : **02 Nov 2025 23:59 AoE**

Envoi : adresse du dépôt GitHub par mail à **jcregin@gmail.com**

- Sujet du mail : `SE github` (exactement)
- Corps : juste l’URL du dépôt

---

## Crédits

Projet développé par **[Mohamed El Amine MAZOUZ](mailto:mohamed-el-amine.mazouz@etu.univ-cotedazur.fr)** (Master 1 IA).
