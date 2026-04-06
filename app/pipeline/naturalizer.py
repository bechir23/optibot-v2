"""Response Naturalizer — data-driven French speech variations.

Transforms discrete actions into natural-sounding French speech:
1. Pre-generated variations (0 cost, 0 latency) — loaded from JSON or fallback
2. Fallback template formatting
3. Contextual transitions with overlap prevention
4. French number formatting (euros in words, long numbers spelled out)
5. Anti-repetition tracking (never same variation twice in a row)
"""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Optional

_DEFAULT_VARIATIONS_PATH = Path(__file__).resolve().parents[2] / "data" / "naturalizer_variations.json"


def _load_variations() -> dict[str, list[str]]:
    """Load variations from JSON file, env override, or fallback."""
    override = os.getenv("OPTIBOT_NATURALIZER_VARIATIONS_PATH")
    for path in [Path(override) if override else None, _DEFAULT_VARIATIONS_PATH]:
        if path and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, list)}
            except (OSError, json.JSONDecodeError):
                pass
    return _FALLBACK_VARIATIONS


_FALLBACK_VARIATIONS: dict[str, list[str]] = {
    "P3_GREET": [
        "Bonjour, je vous appelle de la part de l'opticien pour le suivi d'un dossier de remboursement.",
        "Bonjour, c'est le gestionnaire de l'opticien. J'appelle pour un suivi de dossier tiers payant.",
        "Bonjour, j'appelle de chez l'opticien au sujet d'un remboursement.",
    ],
    "P3_GIVE_PATIENT": [
        "C'est pour le dossier de {patient_name}.",
        "C'est concernant {patient_name}.",
        "Le dossier concerne {patient_name}.",
    ],
    "P3_GIVE_BORDEREAU": [
        "Le numero de bordereau, c'est le {dossier_ref}.",
        "Le bordereau, j'ai le numero {dossier_ref}.",
        "Le numero du bordereau c'est... {dossier_ref}.",
    ],
    "P3_GIVE_NIR": [
        "Le numero de secu c'est le {nir}.",
        "Le numero de securite sociale... c'est le {nir}.",
        "Son numero de secu, j'ai le {nir}.",
    ],
    "P3_GIVE_MONTANT": [
        "Le montant en attente cote mutuelle c'est {montant} euros.",
        "On a {montant} euros en attente cote complementaire.",
        "Le montant qu'on attend c'est {montant} euros.",
    ],
    "P3_NO_DATA": [
        "Je n'ai pas cette info sous les yeux. Vous pouvez retrouver le dossier avec le nom et la date ?",
        "Ca, je ne l'ai pas ici. Est-ce que le nom du patient et la date suffisent ?",
        "Je n'ai pas ce numero malheureusement. On peut chercher avec le nom ?",
    ],
    "P3_ASK_STATUS": [
        "Vous pouvez me dire ou en est ce dossier ?",
        "Ce dossier, il en est ou exactement ?",
        "Au niveau du dossier, vous pouvez me dire ou ca en est ?",
        "Juste pour le suivi, vous avez le statut du dossier ?",
    ],
    "P3_ASK_REASON": [
        "Pour quelle raison le remboursement n'a pas ete effectue ?",
        "Et pourquoi c'est bloque exactement ?",
        "OK. Vous savez ce qui bloque sur ce dossier ?",
        "Et euh, qu'est-ce qui empeche le remboursement ?",
    ],
    "P3_ASK_MISSING_DOC": [
        "Y a-t-il des pieces complementaires a fournir ?",
        "D'accord. Est-ce qu'il manque des documents de notre cote ?",
        "OK. Vous avez besoin qu'on renvoie quelque chose ?",
    ],
    "P3_ASK_TIMELINE": [
        "Dans quel delai peut-on esperer le reglement ?",
        "D'accord. Et en termes de delai, on parle de combien de temps ?",
        "OK. Vous avez une idee du delai pour le virement ?",
        "Et du coup, ca va prendre combien de temps a peu pres ?",
    ],
    "P3_ASK_AMOUNT": [
        "Quel est le montant de remboursement prevu ?",
        "D'accord. Et le montant qui va etre verse, c'est combien ?",
        "OK. Vous pouvez me confirmer le montant du remboursement ?",
    ],
    "P3_ASK_REFERENCE": [
        "Vous avez une reference de dossier a me communiquer ?",
        "D'accord. Est-ce que vous avez un numero de reference que je peux noter ?",
        "OK. Il y a une reference de dossier de votre cote ?",
    ],
    "P3_CLARIFY": [
        "Excusez-moi, pouvez-vous preciser ce point ?",
        "Pardon, j'ai pas bien compris cette partie. Vous pouvez repreciser ?",
        "Euh, desole, je n'ai pas bien saisi. Vous pouvez repeter ?",
    ],
    "P3_REPEAT": [
        "Pardon, je n'ai pas bien entendu. Pouvez-vous repeter ?",
        "Excusez-moi, la ligne est pas top. Vous pouvez repeter ?",
        "Desole, j'ai pas capte. Vous pouvez redire ?",
    ],
    "P3_ACK": [
        "D'accord, je note.",
        "OK tres bien, merci.",
        "Entendu, c'est note.",
        "Ah d'accord, je vois.",
        "OK parfait, merci pour l'info.",
    ],
    "P3_ACK_WAIT": [
        "Entendu, je rappellerai apres ce delai.",
        "D'accord, on patiente alors. Je rappellerai.",
        "OK, c'est note. Je reprendrai contact apres.",
    ],
    "P3_ACK_TRANSFER": [
        "D'accord, je reste en ligne pour le transfert.",
        "OK pas de souci, je patiente pour le transfert.",
        "Tres bien, je reste en ligne.",
    ],
    "P3_CONFIRM": [
        "Je confirme, c'est bien ca.",
        "Oui c'est correct.",
        "C'est bien ca, oui.",
    ],
    "P3_SILENCE": [],
    "P3_ASK_NAME": [
        "Vous etes qui, s'il vous plait, pour la reference ?",
        "Et euh, je peux avoir votre nom pour mon dossier ?",
        "D'accord. Je note votre nom pour le suivi, vous etes ?",
    ],
    "P3_THANK": [
        "Merci beaucoup pour ces informations.",
        "OK super, merci beaucoup.",
        "Tres bien, merci pour votre aide.",
        "Parfait, merci pour tout.",
    ],
    "P3_GOODBYE": [
        "Bonne journee, au revoir.",
        "Merci, bonne journee.",
        "Au revoir et bonne continuation.",
        "Merci beaucoup, au revoir.",
    ],
    "P3_SUMMARIZE": [
        "Pour resumer : {summary}. C'est bien ca ?",
        "OK alors si je recapitule : {summary}. J'ai bien tout ?",
        "D'accord. Donc en resume : {summary}. C'est correct ?",
    ],
}

VARIATIONS: dict[str, list[str]] = _load_variations()

TRANSITIONS_AFTER_QUESTION = ["", "", "Oui, ", ""]
TRANSITIONS_AFTER_LONG_INFO = ["", "", "D'accord. ", ""]
TRANSITIONS_AFTER_SHORT = ["", "", "", ""]
TRANSITIONS_AFTER_HOLD = ["", "Oui je suis toujours la. ", ""]

_NOISE_WORDS = {"je", "le", "la", "les", "un", "une", "de", "du", "des", "et", "en", "au"}


class ResponseNaturalizer:
    """Transforms a discrete action into natural French speech."""

    def __init__(self):
        self._used: dict[str, set[int]] = {}
        self._last_backchannel = ""

    async def naturalize(
        self,
        action_id: str,
        template: str,
        context: dict,
        last_utterance: str = "",
        from_hold: bool = False,
    ) -> str:
        if action_id == "P3_SILENCE":
            return ""

        response = self._pick_variation(action_id, context)
        if not response:
            try:
                response = template.format(**context)
            except KeyError:
                response = template

        response = self._add_transition(response, last_utterance, from_hold)
        response = format_numbers_for_speech(response)
        return response

    def pick_backchannel(self) -> str:
        options = ["mmh mmh", "d'accord", "oui je vois", "ah OK", "oui oui", "entendu"]
        available = [o for o in options if o != self._last_backchannel]
        choice = random.choice(available)
        self._last_backchannel = choice
        return choice

    def _pick_variation(self, action_id: str, context: dict) -> Optional[str]:
        variations = VARIATIONS.get(action_id, [])
        if not variations:
            return None

        used_indices = self._used.get(action_id, set())
        unused = [(i, v) for i, v in enumerate(variations) if i not in used_indices]
        if not unused:
            self._used[action_id] = set()
            unused = list(enumerate(variations))

        idx, text = random.choice(unused)
        self._used.setdefault(action_id, set()).add(idx)

        try:
            return text.format(**context)
        except KeyError:
            return text

    def _add_transition(self, response: str, last_utterance: str, from_hold: bool) -> str:
        if from_hold:
            return random.choice(TRANSITIONS_AFTER_HOLD) + response
        if not last_utterance:
            return response

        if "?" in last_utterance:
            transition = random.choice(TRANSITIONS_AFTER_QUESTION)
        elif len(last_utterance) > 60:
            transition = random.choice(TRANSITIONS_AFTER_LONG_INFO)
        else:
            transition = random.choice(TRANSITIONS_AFTER_SHORT)

        if not transition.strip():
            return response

        transition_words = [
            w for w in re.split(r"[\s,.']+", transition.strip().lower()) if w and w not in _NOISE_WORDS
        ]
        response_start = re.split(r"[\s,.']+", response[:40].strip().lower())
        response_start_words = [w for w in response_start[:4] if w]

        for tw in transition_words:
            if tw in response_start_words:
                return response

        return transition + response

    def reset(self):
        self._used.clear()
        self._last_backchannel = ""


def format_numbers_for_speech(text: str) -> str:
    """Convert numbers to spoken French format with pauses."""
    try:
        from num2words import num2words as _n2w

        def _euros(m):
            eur = int(m.group(1))
            cts = int(m.group(2)) if m.group(2) else 0
            result = _n2w(eur, lang='fr') + " euros"
            if cts:
                result += " et " + _n2w(cts, lang='fr') + " centimes"
            return result

        text = re.sub(r'(\d+)[.,](\d{1,2})\s*(?:euros?|EUR)', _euros, text)
        text = re.sub(r'(\d+)\s*(?:euros?|EUR)', lambda m: _n2w(int(m.group(1)), lang='fr') + " euros", text)
    except ImportError:
        pass

    def _spell_long_number(m):
        digits = m.group(0)
        if len(digits) >= 6:
            groups = []
            for i in range(0, len(digits), 3):
                groups.append(", ".join(digits[i:i+3]))
            return "... ".join(groups)
        return digits

    text = re.sub(r'\b\d{6,}\b', _spell_long_number, text)
    return text
