"""Couture de génération du relais — H1 (stub) → H2 (provider réel).

`Narrator` est le seul point à remplacer en H2 : `CannedNarrator` →
`LLMNarrator`. Le router et le contrat ne bougent pas (« swap = une ligne »).

Cécité au canon (invariant #2) : le narrateur ne reçoit que le `packet` déjà
validé. Il n'a aucune autre source ; il n'y a aucun secret dans le paquet,
seulement des étiquettes neutres `revealable` / `withhold`.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

from pipelines.evaluation.providers import (
    ChatMessage,
    CompletionRequest,
    Provider,
    get_provider,
)


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


class LLMNarrator:
    """H2 — génération best-of-N via un provider LLM, à partir du SEUL paquet.

    Cécité au canon (invariant #2) : le prompt est dérivé champ par champ du
    paquet déjà validé, et rien d'autre n'entre. `withhold` n'est rendu que
    comme une liste d'**intitulés à taire** — le paquet ne contient aucun
    secret, le prompt ne fait que refléter cette absence.

    Le Hub ne trie ni ne filtre les candidats (invariant #3) : le verifier
    reste côté CN.
    """

    _SYSTEM_PROMPT = (
        "Tu es le narrateur d'une scène de jeu de rôle. On te donne un cadre, un "
        "personnage qui agit, l'action du joueur, et des contraintes de forme. Tu "
        "rends UN SEUL beat de narration, à la voix du personnage. Règles : tu "
        "n'utilises que les faits listés comme révélables, dans la limite du budget "
        "indiqué. Les sujets listés comme « à taire » existent mais tu n'en connais "
        "pas le contenu — tu ne dois rien inventer à leur sujet ni laisser entendre "
        "que tu sais. Tu respectes le registre et le ratio demandés. Tu évites les "
        "patrons structurels interdits. Tu ne préfigures pas, tu ne résous pas la scène."
    )

    def __init__(
        self,
        *,
        provider: Provider | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        # Provider résolu paresseusement : create_app ne doit pas échouer au
        # boot si aucune clé n'est configurée — l'erreur surgit à l'appel.
        self._provider = provider
        self.model = model or os.environ.get("MUSES_NARRATE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        self.temperature = (
            float(temperature)
            if temperature is not None
            else float(os.environ.get("MUSES_NARRATE_TEMPERATURE", "0.8"))
        )
        self.max_tokens = (
            int(max_tokens)
            if max_tokens is not None
            else int(os.environ.get("MUSES_NARRATE_MAX_TOKENS", "256"))
        )

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    def _system_prompt(self) -> str:
        return self._SYSTEM_PROMPT

    def render_packet(self, packet: dict) -> str:
        """Sérialise le paquet en prompt utilisateur — uniquement ses champs.

        Tolérant aux deux formes de paquet (placeholder Hub et schéma CN réel) :
        `cadre` str ou objet, `form.budget`/`budget_revelation`,
        `form.shapes_interdites`/`interdit_shape`.

        Préparé pour deux champs CN à venir (Hub-C #93), consommés dès qu'ils
        apparaissent dans le schéma vendorisé, ignorés tant qu'ils sont absents :
        `language` (BCP-47, langue de rédaction) et `rapport` (variant
        `RapportKind`, ex. `closure`). Les deux décrivent la FORME, pas le canon
        — le narrateur reste aveugle. Ils ne sont PAS hard-typés ici (invariant
        #4) : `language` est repris tel quel, `rapport` est rendu VERBATIM, donc
        n'importe quel variant atteint le prompt sans « défaut silencieux ».
        """
        lines: list[str] = []

        # Langue de rédaction. Absente aujourd'hui (hors schéma) → le modèle
        # infère comme avant ; présente → elle pilote la langue sans devinette.
        language = packet.get("language")
        if language:
            lines.append(
                f"Langue de rédaction : {language} — rends la narration dans cette langue."
            )

        # Nature du rapport (RapportKind). Rendu verbatim : `closure` ou tout
        # futur variant est reflété tel quel, aucun enum figé côté Hub.
        rapport = packet.get("rapport")
        if rapport:
            lines.append(f"Nature du rapport (beat) : {rapport}")

        cadre = packet.get("cadre")
        if isinstance(cadre, dict):
            parts = [str(cadre[k]) for k in ("lieu", "ambiance", "presents") if cadre.get(k)]
            if parts:
                lines.append("Cadre : " + " — ".join(parts))
        elif cadre:
            lines.append(f"Cadre : {cadre}")

        loc = packet.get("locuteur") or {}
        if loc:
            lines.append(
                f"Locuteur : {loc.get('nom', '?')} (voix : {loc.get('voix', '?')})"
            )
        if packet.get("action_joueur"):
            lines.append(f"Action du joueur : {packet['action_joueur']}")
        hearing = packet.get("hearing")
        if hearing:
            # Contrat CN : `hearing` est une string. On tolère aussi une liste.
            rendered = hearing if isinstance(hearing, str) else " ; ".join(hearing)
            lines.append(f"Perçu / entendu : {rendered}")
        move = packet.get("move") or packet.get("mouvement")
        if move:
            lines.append(f"Mouvement du locuteur ce beat : {move}")
        if packet.get("revealable"):
            lines.append("Faits révélables (utilisables) : " + " ; ".join(packet["revealable"]))
        if packet.get("withhold"):
            # Étiquettes neutres uniquement — jamais de contenu (invariant #2).
            lines.append(
                "Sujets à TAIRE (intitulés seulement, contenu inconnu, ne rien "
                "inventer ni laisser entendre que tu sais) : "
                + " ; ".join(packet["withhold"])
            )

        form = packet.get("form") or {}
        if form:
            budget = form.get("budget_revelation", form.get("budget"))
            shapes = form.get("interdit_shape", form.get("shapes_interdites"))
            fl: list[str] = []
            if form.get("registre"):
                fl.append(f"registre={form['registre']}")
            if budget is not None:
                fl.append(f"budget_revelation={budget}")
            if form.get("ratio") is not None:
                fl.append(f"ratio_nonverbal={form['ratio']}")
            if shapes:
                fl.append("patrons_interdits=" + ", ".join(shapes))
            if fl:
                lines.append("Forme : " + " ; ".join(fl))

        return "\n".join(lines)

    def narrate(self, packet: dict, n: int) -> list[str]:
        system = self._system_prompt()
        user = self.render_packet(packet)
        candidates: list[str] = []
        for _ in range(n):  # best-of-N = N générations indépendantes (temp > 0)
            request = CompletionRequest(
                model=self.model,
                messages=[
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=user),
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            resp = self.provider.chat_completion(request)  # peut lever ProviderError
            candidates.append(resp.content.strip())
        return candidates
