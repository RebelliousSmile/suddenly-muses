"""Couture de génération du relais — H1 (stub) → H2 (provider réel).

`Narrator` est le seul point à remplacer en H2 : `CannedNarrator` →
`LLMNarrator`. Le router et le contrat ne bougent pas (« swap = une ligne »).

Cécité au canon (invariant #2) : le narrateur ne reçoit que le `packet` déjà
validé. Il n'a aucune autre source ; il n'y a aucun secret dans le paquet,
seulement des étiquettes neutres `revealable` / `withhold`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Narrator(Protocol):
    """Génère N candidats narrateur à partir du seul paquet de scène."""

    def narrate(self, packet: dict, n: int) -> list[str]: ...


class CannedNarrator:
    """Stub H1 : N candidats déterministes, sans appel réseau ni LLM.

    Un candidat est volontairement **fuyard** : il mentionne un sujet
    `withhold`, pour que le verifier (côté CN) ait quelque chose à écarter en
    test. Le Hub, lui, ne filtre rien (invariant #3) : il renvoie tout brut.
    """

    def narrate(self, packet: dict, n: int) -> list[str]:
        nom = (packet.get("locuteur") or {}).get("nom") or "Le personnage"
        withhold = packet.get("withhold") or []
        leak_index = n - 1  # le dernier candidat fuit, s'il y a de quoi fuir
        candidates: list[str] = []
        for i in range(n):
            if i == leak_index and withhold:
                candidates.append(
                    f"{nom} laisse filtrer une allusion à : {withhold[0]}."
                )
            else:
                candidates.append(
                    f"{nom} répond, ancré dans la scène, sans rien trahir."
                )
        return candidates
