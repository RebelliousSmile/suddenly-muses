> ⛔ **OBSOLÈTE — NE PAS EXÉCUTER.** Archivé le 2026-06-03.
>
> Ce plan décrit une architecture **LoRA multi-adapters** (stacking PEFT, base Qwen2.5-7B, inférence GPU, providers Together/Fireworks) **supprimée par le pivot D14** (« pivot complet vers tables + ML léger »). Aucun des fichiers qu'il vise n'existe plus : `scripts/infer.py`, `scripts/list_models.py`, dossier `models/`, deps `peft`/`torch`/`transformers`. Muse recombine désormais des fragments JSONL de façon déterministe (CPU-only, zéro fine-tuning).
>
> Conservé uniquement comme **trace historique** de l'approche abandonnée.

---

# Stacking + Évaluation — Plan d'Implémentation

> **For Hermes:** Execute task-by-task. Each task produces one commit.

**Goal:** Refonte du README, scripts (`list_models.py`, `infer.py`) et création d'un pipeline d'évaluation complet pour le modèle de stacking LoRA multi-adapters.

**Architecture:** 3 axes orthogonaux — Feature (dialogue, action, description...), Univers (fantasy, cyberpunk...), Style (combat, romance, intrigue...). Les adapters s'additionnent à l'inférence via `multipliers`.

**Tech Stack:** Python 3.12, `peft`, `transformers`, `torch`, `pytest`, `jsonl`, `argparse`.

---

## Contexte

Le repo `suddenly-muses` contient actuellement:
- `README.md` — 2 axes (Feature × Style), single adapter, pas de stacking
- `scripts/list_models.py` — Registry single adapter
- `scripts/infer.py` — Charge **un seul** PeftModel
- `aidd_docs/memory/external/` — `lora-fondements.md`, `use-cases.md` (déjà poussés)
- **AUCUN test** — ni unitaire, ni d'évaluation de modèles

---

## Task 1: Refonte README.md — modèle stacking 3 axes

**Objective:** Remplacer la documentation 2-axes/single-adapter par la structure stacking 3 axes avec exemples multipliers.

**Files:**
- Modify: `README.md`

**Changements:**

1. **Header:** Ajouter "LoRA stacking pour Suddenly" — mentionner 3 axes
2. **Section "3 axes":**
   - Axe 1 — **Feature** (ce qu'on génère): dialogue (#77), action (#78), description (#79), pensée (#80), cohérence (#81-82), résumé (#83), fédération (#84)
   - Axe 2 — **Univers** (genre/lore): fantasy-médiévale, cyberpunk, steampunk, horreur-gothique...
   - Axe 3 — **Style** (rythme/ton): combat, romance, intrigue, exploration, politique, quotidien
3. **Nouvelle section "Stacking multi-adapters":**
   - Schéma: $W_{final} = W_{base} + \alpha_1 \Delta W_{feature} + \alpha_2 \Delta W_{univers} + \alpha_3 \Delta W_{style}$
   - Table de multipliers: équilibré (1.0/1.0/1.0), univers dominant (1.5/0.8/0.8), scène dominante (0.8/1.5/1.5)
   - Avertissement: multipliers > 2.0 risquent catastrophic forgetting
4. **Sections exemples — un par feature avec stacking:**
   - Chaque feature (dialogue, action, description, etc.) a un exemple CLI montrant `--stack`
5. **Nouveau schéma d'usage:**
   ```bash
   python scripts/infer.py \
     --stack suddenly-dialogue:1.0 suddenly-fantasy:1.2 combat:0.8 \
     --prompt "Contexte: Combat en forêt. Style: combat. Style narration: action. ..."
   ```
   - Le même exemple avec `--base` seul vs `--stack`

**Vérification:** `cat README.md | grep -c "stack"` → ≥ 5 occurrences. `cat README.md | grep -c "multiplier"` → ≥ 3.

**Commit:**
```bash
git add README.md
git commit -m "docs: rewrite README for 3-axis stacking LoRA with multipliers"
```

---

## Task 2: Mise à jour `scripts/list_models.py` — support stacking

**Objective:** Le registry doit afficher les adapters par axe (Feature, Univers, Style) et supporter l'affichage des stacks possibles.

**Files:**
- Modify: `scripts/list_models.py`

**Nouvelle structure du dict FEATURES:**

```python
FEATURES = {
    "suddenly-dialogue": {
        "axis": "feature",
        "issue": "#77",
        "desc": "Suggestion de dialogue pour un personnage",
    },
    "suddenly-action": {
        "axis": "feature",
        "issue": "#78",
        "desc": "Suggestion d'action pour un personnage",
    },
    # ... 8 features
}

UNIVERS = {
    "fantasy-medievale": {
        "axis": "univers",
        "desc": "Épées, magie, féodalité, royaumes",
    },
    "cyberpunk": {
        "axis": "univers",
        "desc": "Techno, mégacorporations, implants",
    },
    # ...
}

STYLES = {
    "combat": {
        "axis": "style",
        "desc": "Escarmouches, batailles, tensions physiques",
    },
    "romance": {
        "axis": "style",
        "desc": "Relations interpersonnelles, tension émotionnelle",
    },
    # ... 6 styles
}
```

**Nouvelles fonctions:**
```python
def list_by_axis(axis):
    """List adapters for a given axis."""

def list_stacks(feature_ids):
    """Show all valid stacks for given feature adapters."""

def main():
    # Affichage en 3 colonnes par axe
    # Option --stack pour afficher les stacks possibles
    # Option --filter feature|univers|style
```

**Vérification:**
```bash
python scripts/list_models.py
# → Affiche 3 sections : Feature / Univers / Style
python scripts/list_models.py --filter feature
# → Affiche uniquement les 8 features
```

**Commit:**
```bash
git add scripts/list_models.py
git commit -m "scripts: add stacking support to list_models registry"
```

---

## Task 3: Mise à jour `scripts/infer.py` — multi-adapter stacking

**Objective:** `infer.py` doit supporter le chargement de N adapters avec des multipliers distincts.

**Files:**
- Modify: `scripts/infer.py`

**Nouvelles options CLI:**
```python
parser.add_argument("--stack", nargs="+", metavar="adapter:multiplier",
    help="List of adapter:multiplier pairs (e.g., suddenly-dialogue:1.0 fantasy:1.2)")
parser.add_argument("--base", default=DEFAULT_BASE, help="Base model")
```

**Nouvelle fonction `load_model_stack`:**

```python
def load_model_stack(adapter_specs: list[dict], base_model: str = DEFAULT_BASE):
    """
    Load base model + N LoRA adapters with distinct multipliers.
    
    adapter_specs: [{"name": "suddenly-dialogue", "weight": 1.0},
                    {"name": "fantasy-medievale", "weight": 1.2}]
    
    Uses PEFT's add_weighted_adapter + load_adapter for stacking.
    """
    print(f"Loading base model: {base_model}...")
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    
    for spec in adapter_specs:
        adapter_name = spec["name"]
        weight = spec["weight"]
        adapter_path = MODELS_DIR / adapter_name
        
        print(f"Loading adapter: {adapter_name} (weight={weight})...")
        
        # PEFT approach for stacking:
        model.load_adapter(adapter_path, adapter_name=adapter_name)
        model.set_adapter(adapter_name)
        model.add_weighted_adapter(
            adapters=[adapter_name],
            weights=[weight],
            target_adapter_name="combined"
        )
    
    model.set_adapter("combined")
    return model, tokenizer
```

**Alternative PEFT stacking (plus simple):**
```python
# Alternative: PEFT native stacking via add_weighted_adapter
# Load each adapter with unique name, then combine
for spec in adapter_specs:
    model.load_adapter(
        str(MODELS_DIR / spec["name"]),
        adapter_name=spec["name"]
    )

model.add_weighted_adapter(
    adapters=[s["name"] for s in adapter_specs],
    weights=[s["weight"] for s in adapter_specs],
    adapter_name="stack"
)
model.set_adapter("stack")
```

**Fallback `load_model` (single adapter) doit rester pour backward compatibilité:**
```python
def load_model(adapter_path, base_model=DEFAULT_BASE):
    """Legacy: load single adapter (backward compat)."""
    # ... same as before ...
```

**Commande:**
```bash
# Single adapter (old way, still works)
python scripts/infer.py --adapter models/suddenly-dialogue --prompt "..."

# Stacking (new way)
python scripts/infer.py --stack suddenly-dialogue:1.0 fantasy:1.2 combat:0.8 --prompt "..."
```

**Commit:**
```bash
git add scripts/infer.py
git commit -m "scripts: add multi-adapter stacking to infer.py with PEFT weighted adapters"
```

---

## Task 4: Créer `data/test-prompts.jsonl` — dataset d'évaluation

**Objective:** Créer un dataset structuré de 50+ prompts pour évaluer les adapters, organisé par axe Feature × Univers × Style.

**Files:**
- Create: `data/test-prompts.jsonl`

**Format JSONL (une ligne par prompt):**
```jsonl
{"id": "feat-dialogue-combat-fantasy", "feature": "dialogue", "univers": "fantasy-medievale", "style": "combat", "prompt": "Le chevalier Brandan entre dans la taverne fumante. Son épée est encore dégoutante du sang de l'orque. Un nain à la barbe tressée l'interpelle d'une voix rauque: « Eh toi, barbouillé de sang, tu as vu passer le mage sombre ? » Réponds en tant que Brandan...", "expected_markers": ["réplique", "dialogue", "verbe de parole", "première personne"], "difficulty": "easy", "language": "fr"}
{"id": "feat-action-romance-cyberpunk", "feature": "action", "univers": "cyberpunk", "style": "romance", "prompt": "La cybernétique de Kira grésille dans la pluie acide de Neo-Tokyo. Un inconnu avec un implant oculaire violet lui tend la main depuis le toit adjacent. Décris son action...", "expected_markers": ["action physique", "verbe d'action", "détail sensoriel"], "difficulty": "medium", "language": "fr"}
```

**Structure du dataset (50 prompts répartis):**

| Feature | Styles couverts | # prompts |
|---|---|---|
| dialogue | combat, romance, intrigue | 6 (2 par style) |
| action | combat, exploration, politique | 6 |
| description | exploration, quotidien, horreur | 6 |
| pensée | intrigue, romance, politique | 6 |
| cohérence-scène | combat, romance, intrigue | 6 |
| cohérence-session | combat, romance, intrigue | 6 |
| résumé | combat, romance, intrigue | 6 |
| federation | - | 2 |
| **Total** | | **50** |

**Champs requis par entrée:**
- `id` — unique (ex: `feat-dialogue-combat-fantasy`)
- `feature` — correspond à un adapter Suddenly
- `univers` — univers testé (fantasy-medievale, cyberpunk, steampunk, etc.)
- `style` — style de narration (combat, romance, intrigue, exploration, politique, quotidien)
- `prompt` — le prompt complet à envoyer au modèle
- `expected_markers` — liste de marqueurs attendus dans la sortie (pour scoring automatique)
- `difficulty` — easy / medium / hard
- `language` — "fr"

**Note:** Les prompts réalistes sont essentiels — ils doivent ressembler à de vrais scénarios RP.

**Vérification:**
```bash
wc -l data/test-prompts.jsonl  → ≥ 50
python -c "import json; [json.loads(l) for l in open('data/test-prompts.jsonl')]; print('OK')"
```

**Commit:**
```bash
git add data/test-prompts.jsonl
git commit -m "data: add 50-eval test prompt dataset for LoRA adapter evaluation"
```

---

## Task 5: Créer `scripts/evaluate.py` — pipeline d'évaluation

**Objective:** Script principal qui charge des prompts tests, fait tourner les adapters (ou stacks), score les résultats selon 5 critères, et génère des rapports.

**Files:**
- Create: `scripts/evaluate.py`
- Create: `scripts/baseline.py` (helper: run base model for comparison)

**Architecture:**

```
scripts/evaluate.py
├── Evaluator class
│   ├── load_prompts(filepath) → list[dict]
│   ├── get_response(prompt, backend, config) → str
│   ├── score_response(prompt, response, criteria) → dict
│   └── generate_report(results, output_dir) → (csv, json)
├── CLI args: --backend, --stack, --batch, --filter, --scoring
└── Main: orchestrate flow
```

**Arguments CLI:**
```python
parser.add_argument("--backend", choices=["local", "api", "simulate"], required=True,
    help="Inference backend: local (vLLM), api (Together), or simulate (mock scores)")
parser.add_argument("--prompts", default="data/test-prompts.jsonl",
    help="Path to test prompts JSONL file")
parser.add_argument("--stack", nargs="+", metavar="adapter:weight",
    help="Stack of adapters to evaluate (e.g., suddenly-dialogue:1.0 fantasy:1.2)")
parser.add_argument("--base-model", default="Qwen/Qwen2.5-7B-Instruct")
parser.add_argument("--batch", action="store_true",
    help="Run all prompts. Default: run one for debugging")
parser.add_argument("--filter", type=str,
    help="Filter by feature (e.g., --filter dialogue)")
parser.add_argument("--scoring", choices=["auto", "llm-judge", "hybrid"], default="auto",
    help="Scoring method: auto (keyword), llm-judge (LLM scores), hybrid (both)")
parser.add_argument("--output-dir", default="reports",
    help="Directory for generated reports")
parser.add_argument("--temperature", type=float, default=0.7)
parser.add_argument("--max-tokens", type=int, default=500)
```

**Critères de scoring (les 5 de l'issue #52):**

```python
CRITERIA = {
    "narrative_coherence": "La réponse suit une narration logique sans contradictions internes.",
    "stylistic_fluency": "Le style est fluide, varié, et adapté au registre demandé.",
    "rp_relevance": "La réponse est pertinente pour le rôleplay (pas hors-sujet).",
    "sensory_immersion": "La réponse contient des détails sensoriels (vue, ouïe, odeur, toucher).",
    "genre_respect": "La réponse respecte le genre/univers spécifié (vocabulaire, contexte).",
}
```

**Score par critère: 1-5 échelle.**

**Mode `simulate`** — retourne scores random ~3.5 pour tester le pipeline (ne pas utiliser comme benchmark réel).

**Mode `auto`** — vérifie les `expected_markers` dans la réponse:
```python
def score_auto(response, expected_markers):
    score = 0
    for marker in expected_markers:
        if marker.lower() in response.lower():
            score += 1
    return min(5, score)
```

**Mode `llm-judge`** — utiliser un modèle de référence (GPT-4o ou Llama-70B) pour scorer:
```python
def score_llm_judge(prompt, response, criteria, judge_model):
    # Build evaluation prompt with criteria + prompt + response
    # Send to judge model
    # Parse numeric scores from output
```

**Mode `hybrid`** — keywords + LLM-judge pour les critères style/qualité.

**Rapports générés:**

`reports/results.csv`:
```csv
id,feature,univers,style,prompt_length,response_length,narrative_coherence,stylistic_fluency,rp_relevance,sensory_immersion,genre_respect,total_score
feat-dialogue-combat-fantasy,dialogue,fantasy-medievale,combat,142,256,4,3,5,3,4,19
...
```

`reports/results.json`:
```json
{
  "metadata": {
    "timestamp": "2026-05-15T15:30:00Z",
    "backend": "local",
    "base_model": "Qwen/Qwen2.5-7B-Instruct",
    "stack": ["suddenly-dialogue:1.0"],
    "scoring": "auto",
    "total_prompts": 50,
    "criteria": {...}
  },
  "results": [
    {
      "id": "feat-dialogue-combat-fantasy",
      "feature": "dialogue",
      "univers": "fantasy-medievale",
      "style": "combat",
      "prompt": "...",
      "response": "...",
      "scores": {
        "narrative_coherence": 4,
        "stylistic_fluency": 3,
        ...
      },
      "total_score": 19
    }
  ]
}
```

**Vérification:**
```bash
# Mode simulate (toujours marche, pas besoin de GPU)
python scripts/evaluate.py --backend simulate --batch

# → Génère reports/results.csv et reports/results.json
# → Affiche résumé: moyenne par critère, total moyen
```

**Commit:**
```bash
git add scripts/evaluate.py scripts/baseline.py data/test-prompts.jsonl
git commit -m "eval: add evaluation pipeline for LoRA stacking with 5-criteria scoring"
```

---

## Task 6: Créer `scripts/baseline.py` — baseline sans adapter

**Objective:** Permet de comparer le modèle base (sans LoRA) avec les adapters et stacks.

**Files:**
- Create: `scripts/baseline.py`

```python
#!/usr/bin/env python3
"""Run evaluation on base model (no LoRA) for comparison."""
import argparse
from evaluate import Evaluator

def main():
    parser = argparse.ArgumentParser(description="Base model baseline evaluation")
    parser.add_argument("--prompts", default="data/test-prompts.jsonl")
    parser.add_argument("--scoring", choices=["auto", "llm-judge", "hybrid"], default="auto")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    
    evaluator = Evaluator()
    results = evaluator.run_baseline(args.prompts, scoring=args.scoring)
    evaluator.generate_report(results, args.output_dir)
    evaluator.print_summary(results, label="BASELINE")

if __name__ == "__main__":
    main()
```

**Usage:**
```bash
# Run base model only
python scripts/baseline.py --scoring auto

# Compare: base vs adapter (run separately, compare CSVs)
python scripts/baseline.py --output-dir reports/base
python scripts/evaluate.py --backend local --stack suddenly-dialogue:1.0 --output-dir reports/dialogue-adapter
```

**Commit:**
```bash
git add scripts/baseline.py
git commit -m "scripts: add baseline evaluation script (base model only, no LoRA)"
```

---

## Task 7: Ajouter `pytest.ini` et tests d'intégration

**Objective:** Créer un setup pytest minimal pour tester les scripts (pas les modèles, mais les scripts eux-mêmes).

**Files:**
- Create: `pytest.ini`
- Create: `tests/test_evaluate.py`
- Create: `tests/test_list_models.py`
- Create: `tests/test_infer_stacking.py`
- Create: `tests/conftest.py`

**`pytest.ini`:**
```ini
[pytest]
pythonpath = .
testpaths = tests
addopts = -v
```

**`tests/conftest.py`:**
```python
import pytest

@pytest.fixture
def sample_prompt():
    return {
        "id": "test-dialogue-combat",
        "feature": "dialogue",
        "univers": "fantasy-medievale",
        "style": "combat",
        "prompt": "Le chevalier Brandan entre dans la taverne...",
        "expected_markers": ["réplique", "dialogue"],
        "difficulty": "easy",
    }

@pytest.fixture
def sample_prompts_file(tmp_path):
    """Create a temp JSONL file with one prompt."""
    p = tmp_path / "test-prompts.jsonl"
    p.write_text('{\"id\": \"t1\", \"feature\": \"dialogue\", \"prompt\": \"test\"}\n')
    return p
```

**`tests/test_list_models.py`:**
```python
import subprocess
import sys

def test_list_models_runs():
    result = subprocess.run(
        [sys.executable, "scripts/list_models.py"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "Feature" in result.stdout or "adapter" in result.stdout.lower()

def test_list_models_filter_feature():
    result = subprocess.run(
        [sys.executable, "scripts/list_models.py", "--filter", "feature"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
```

**`tests/test_infer_stacking.py`:**
```python
import subprocess
import sys

def test_infer_help():
    result = subprocess.run(
        [sys.executable, "scripts/infer.py", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--stack" in result.stdout

def test_infer_stack_syntax():
    result = subprocess.run(
        [sys.executable, "scripts/infer.py", "--stack", "dialogue:1.0"],
        capture_output=True, text=True
    )
    # Should fail gracefully (no model), not crash with syntax error
    assert result.returncode != 2  # not argparse error
```

**`tests/test_evaluate.py`:**
```python
from scripts.evaluate import Evaluator

def test_evaluator_loads_prompts(sample_prompts_file):
    ev = Evaluator()
    prompts = ev.load_prompts(str(sample_prompts_file))
    assert len(prompts) == 1
    assert prompts[0]["id"] == "t1"

def test_evaluator_score_auto():
    ev = Evaluator()
    response = "Le chevalier dit: « Bonjour ! » et dégaine son épée."
    markers = ["réplique", "dialogue", "verbe de parole"]
    score = ev.score_auto(response, markers)
    assert score >= 1  # at least some markers should match

def test_evaluator_simulate_backend():
    ev = Evaluator()
    results = ev.run_simulate(1)  # 1 prompt
    assert len(results) == 1
    assert 0 <= results[0]["total_score"] <= 25  # 5 criteria × 5 max
```

**Vérification:**
```bash
pytest tests/ -v
# → 5-8 tests, tous PASS (mode simulate, pas de modèle requis)
```

**Commit:**
```bash
git add pytest.ini tests/
git commit -m "tests: add pytest setup with integration tests for scripts and evaluate pipeline"
```

---

## Task 8: Mettre à jour `README.md` — section évaluation

**Objective:** Documenter l'évaluation dans le README (commandes, critères, interprétation).

**Files:**
- Modify: `README.md` (append à la fin)

**Nouvelle section à ajouter:**

```markdown
## Évaluation des modèles

Le pipeline d'évaluation permet de comparer base model vs adapters vs stacks.

```bash
# 1. Évaluer en mode simulation (pour tester le pipeline)
python scripts/evaluate.py --backend simulate --batch

# 2. Évaluer un adapter spécifique
python scripts/evaluate.py --backend local --stack suddenly-dialogue:1.0 --batch

# 3. Évaluer un stack
python scripts/evaluate.py --backend local --stack suddenly-dialogue:1.0 fantasy:1.2 combat:0.8 --batch

# 4. Baseline sans LoRA
python scripts/baseline.py --scoring auto
```

### Critères de scoring (rubrique #52)

| Critère | Description | Poids |
|---|---|---|
| Cohérence narrative | La réponse suit une narration logique sans contradictions | ×1.5 |
| Fluidité stylistique | Style fluide, varié, adapté au registre | ×1.5 |
| Pertinence RP | Réponse pertinente, pas hors-sujet | ×2.0 |
| Immersion sensorielle | Détails sensoriels (vue, ouïe, odorat, toucher) | ×1.0 |
| Respect du genre | Vocabulaire et contexte adaptés au genre | ×1.0 |

**Score total:** max 25 points. Cible ≥ 15/25 pour un adapter utile.

### Interprétation des résultats

- **≥ 20/25:** Excellent — l'adapter ajoute de la valeur significative
- **15-19/25:** Bon — l'adapter est fonctionnel mais peut être amélioré
- **10-14/25:** Moyen — l'adapter a un impact limité
- **< 10/25:** Insuffisant — l'adapter n'ajoute pas de valeur

Les rapports sont générés dans `reports/results.csv` et `reports/results.json`.
```

**Commit:**
```bash
git add README.md
git commit -m "docs: add model evaluation section to README with scoring criteria"
```

---

## Task 9: Push final

**Objective:** Pousser tous les changements.

```bash
git push origin main
```

---

## Résumé des fichiers crénis/modifiés

| Fichier | Action | Description |
|---|---|---|
| `README.md` | Modify | Refonte 3 axes stacking + section évaluation |
| `scripts/list_models.py` | Modify | Registry multi-axe avec support stacking |
| `scripts/infer.py` | Modify | Multi-adapter stacking avec multipliers PEFT |
| `scripts/evaluate.py` | Create | Pipeline évaluation principal |
| `scripts/baseline.py` | Create | Évaluation baseline sans LoRA |
| `data/test-prompts.jsonl` | Create | 50 prompts de test organisés |
| `pytest.ini` | Create | Configuration pytest |
| `tests/conftest.py` | Create | Fixtures partagées |
| `tests/test_list_models.py` | Create | Tests registry |
| `tests/test_infer_stacking.py` | Create | Tests stacking syntaxe |
| `tests/test_evaluate.py` | Create | Tests pipeline évaluation |

**Total:** 11 fichiers (1 modifié 3x, 7 créés, 1 commit final push).

**Ordre d'exécution recommandé:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9

**Vérification finale:**
```bash
# Tous les scripts doivent passer --help
python scripts/list_models.py --help
python scripts/infer.py --help
python scripts/evaluate.py --help
python scripts/baseline.py --help

# Les tests doivent passer (simulate mode)
pytest tests/ -v

# README doit être cohérent
grep -c "stack" README.md  → ≥ 5
```
