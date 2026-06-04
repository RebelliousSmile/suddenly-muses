"""Cache d'embeddings .npy par table, modèle injectable.

Voir data-format.md §Embeddings. Le mapping `id ↔ index de ligne` est porté
par l'ordre du JSONL : ligne `i` du JSONL = ligne `i` du `.npy`.

Le modèle d'embedding est injectable (interface `Encoder`). Le défaut est un
sentence-transformer multilingue CPU-friendly chargé paresseusement ; les
tests utilisent `StubEncoder` (déterministe, sans dépendance externe).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np

from muses.schemas.row import Row
from muses.tables.jsonl_io import iter_rows


DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DIM = 384  # dimension du modèle par défaut


class Encoder(Protocol):
    """Interface minimale d'un encodeur de texte."""

    dim: int

    def encode(self, texts: list[str]) -> np.ndarray:
        """Renvoie un array (n, dim) float32."""
        ...


class StubEncoder:
    """Encodeur déterministe sans dépendance externe, pour tests.

    Hash MD5 du texte → vecteur reproductible. Pas sémantique, mais stable et
    utile pour tester les flux d'I/O sans charger sentence-transformers.
    """

    def __init__(self, dim: int = 16):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            digest = hashlib.md5(text.encode("utf-8")).digest()
            # Étire le digest sur self.dim float32 dans [-1, 1]
            for j in range(self.dim):
                byte = digest[j % len(digest)]
                out[i, j] = (byte / 127.5) - 1.0
        return out


class SentenceTransformerEncoder:
    """Wrapper paresseux autour de sentence-transformers.

    Le chargement du modèle (~120MB) ne se fait qu'au premier appel à `encode`.
    Permet d'importer ce module sans payer le coût tant qu'on n'embed rien.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model_name = model_name
        self._model = None
        # On expose `dim` connu pour le modèle par défaut ; redéfini après load
        # si le modèle est différent.
        self.dim = DEFAULT_DIM

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers n'est pas installé. "
                "Install via `pip install -e .[embeddings]` ou utilise StubEncoder."
            ) from exc
        # Force CPU explicitly: the deployment target is CPU-only and a few
        # recent torch/transformers combinations have been observed to default
        # into meta-tensor / device-mapping paths when no device is pinned.
        self._model = SentenceTransformer(self.model_name, device="cpu")
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        return np.asarray(self._model.encode(texts, show_progress_bar=False), dtype=np.float32)


class EmbeddingsCache:
    """Persistance des embeddings d'une table dans un fichier .npy."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> np.ndarray:
        return np.load(self.path)

    def save(self, embeddings: np.ndarray) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.save(self.path, embeddings)

    def append(self, new_embeddings: np.ndarray) -> None:
        """Ajoute des embeddings à la fin du cache. Crée si absent."""
        if self.exists():
            existing = self.load()
            if existing.shape[1] != new_embeddings.shape[1]:
                raise ValueError(
                    f"Dimension mismatch: existant {existing.shape[1]}, "
                    f"nouveau {new_embeddings.shape[1]}"
                )
            stacked = np.vstack([existing, new_embeddings])
        else:
            stacked = new_embeddings
        self.save(stacked)


def rebuild_for_table(jsonl_path: Path, npy_path: Path, encoder: Encoder) -> int:
    """Recalcule tous les embeddings d'une table depuis son JSONL.

    Renvoie le nombre de rows embed. L'ordre des lignes du .npy match l'ordre
    du JSONL.
    """
    texts = [row.embeddable_text() for row in iter_rows(jsonl_path)]
    if not texts:
        # Table vide : on persiste un array de la bonne forme
        empty = np.zeros((0, encoder.dim), dtype=np.float32)
        EmbeddingsCache(npy_path).save(empty)
        return 0
    embeddings = encoder.encode(texts)
    EmbeddingsCache(npy_path).save(embeddings)
    return len(texts)
