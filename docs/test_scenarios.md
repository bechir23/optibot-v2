# Test Scenario Library: French Optician Voice Agent

32 scenarios covering the full call lifecycle for mutuelle reimbursement follow-up.
Each scenario has: a verbatim French trigger phrase, expected agent behavior,
hallucination risk, and a machine-verifiable assertion.

Sourced from tiers payant domain research (Extencia, Tiers Payant Assistance,
mutuelle rejection code databases, French call center training scripts).

## Category 1: Identification (5 scenarios)

| # | Scenario | Mutuelle says | Agent should | Assertion |
|---|---|---|---|---|
| S1.1 | Found immediately | "J'ai bien le dossier de M. Dupont" | Confirm match, proceed | Confirmation step before status query |
| S1.2 | NIR required | "Vous avez le numero de securite sociale?" | Call give_nir tool | NIR matches database, no fabricated digits |
| S1.3 | DOB required | "Pouvez-vous confirmer la date de naissance?" | Call give_date_of_birth | French date format (DD/MM/YYYY) |
| S1.4 | Not found | "Aucun assure a ce nom" | Log wrong_mutuelle, end | No retry loop, max 1 attempt |
| S1.5 | Multiple matches | "J'ai deux Dupont, nee en 72 et 85" | Disambiguate with DOB | Explicit DOB before mutuelle confirms |

## Category 2: Reimbursement Status (9 scenarios)

| # | Scenario | Mutuelle says | Agent should | Assertion |
|---|---|---|---|---|
| S2.1 | In progress | "En cours, recu le 15 mars" | Extract status + date, ask timeline | received_date + expected_delay present |
| S2.2 | Already paid | "Virement le 2 avril, 187,50 euros" | Extract amount precisely | amount=187.50 (not 18750) |
| S2.3 | Not found | "Aucune facture, Noemie ou papier?" | Log inexistant, flag resubmission | No hallucinated reference numbers |
| S2.4 | Rejection: LPP | "Code LPP 2243339 non conforme" | Extract code + motif | LPP code captured verbatim |
| S2.5 | Rejection: rights | "Droits non ouverts a la date" | Extract motif, don't argue | Distinguishes AMO vs AMC |
| S2.6 | Rejection: Rx expired | "Ordonnance de plus de 5 ans" | Log motif, don't dispute | No dispute in transcript |
| S2.7 | Rejection: renewal | "Dernier equipement 12/01/2025, 2 ans" | Extract dates + delay | Both dates present |
| S2.8 | Partial payment | "120 sur 210, depassement monture" | Extract both amounts + motif | status=paiement_partiel |
| S2.9 | Missing docs | "En attente ordonnance originale" | Extract which document | missing_doc field populated |

## Category 3: Obstacles (7 scenarios)

| # | Scenario | Mutuelle says | Agent should | Assertion |
|---|---|---|---|---|
| S3.1 | Call back later | "Systeme en maintenance, rappelez demain" | Log + schedule retry | Clean termination, retry within 24h |
| S3.2 | Department transfer | "Je vous transfere, ne quittez pas" | Wait, re-introduce after transfer | Re-states purpose after transfer |
| S3.3 | Extended hold | [hold music 8 min] | Stay silent throughout | No utterances during hold music |
| S3.4 | IVR no human | "Tapez 1 remboursements, 2 adhesions" | DTMF + max 3 attempts | DTMF in log, gives up after 3 |
| S3.5 | Voicemail | "Laissez message apres le bip" | Hang up, NO message | No patient data after voicemail detection |
| S3.6 | Agent confused | "Vous etes un robot?" | Rephrase, then escalate | Max 2 rephrase attempts |
| S3.7 | Missing info | "Il me faut le numero de facture" | State "je n'ai pas cette info" | No fabricated data |

## Category 4: Resolution (6 scenarios)

| # | Scenario | Mutuelle says | Agent should | Assertion |
|---|---|---|---|---|
| S4.1 | Timeline | "Dix jours ouvres" | Extract delay + type | delay_type=business_days |
| S4.2 | Reference | "Reference REC-2026-04-7823" | Extract + read back | Reference matches, readback present |
| S4.3 | Name | "Madame Lefevre, service prestations" | Extract name + department | Both fields populated |
| S4.4 | Resend doc | "Renvoyez la feuille de soins" | Extract action + document | pending_action non-empty |
| S4.5 | Correct + retransmit | "Code LPP errone, corrigez et retransmettez" | Distinguish from simple resend | action=correct_and_retransmit |
| S4.6 | Supervisor | "Il faudrait qu'un responsable regarde" | Request transfer or callback | Escalation attempt before closing |

## Category 5: Edge Cases (5 scenarios)

| # | Scenario | Mutuelle says | Agent should | Assertion |
|---|---|---|---|---|
| S5.1 | Merger (MGEN/LMDE) | "LMDE integree a MGEN, ancien numero invalide" | Log merger, flag update | No retry with obsolete ID |
| S5.2 | CPAM change | "Assure a change de caisse" | Distinguish AMO from AMC | Clarifies AMC status before ending |
| S5.3 | Portabilite | "Droits en portabilite, expirent le 30 juin" | Extract expiry date | Date extracted, urgency if <30d |
| S5.4 | 100% Sante | "Classe B, pas du 100% Sante" | Extract panier=B | No false promise of zero RAC |
| S5.5 | AMO/AMC confusion | "C'est la part Secu, pas nous" | Acknowledge, redirect | No repeated AMO questions to AMC |

## Persona Assignment

Each scenario can be run with any of the 4 dual-agent personas:

| Persona | Style | Best for |
|---|---|---|
| Sophie (Harmonie) | Cooperative, professional | S1.1, S2.1, S2.2, S4.1-S4.3 |
| Marc (MGEN) | Strict, formal, demands NIR | S1.2, S1.3, S2.4-S2.7, S5.1 |
| Catherine (Almerys) | Rushed, transfers often | S3.2, S3.4, S4.6, S5.2 |
| Jean (Viamedis) | Methodical, long holds | S3.3, S2.8, S2.9, S4.4-S4.5 |

## Usage with Dual-Agent Test Harness

```python
# In tests/e2e_dual_real_room.py, add to persona system_prompt:
# "When the opticien agent asks about patient status, respond with:
#  'La facture a ete rejetee, motif code LPP non conforme, code 2243339'"
```

Each scenario's "Mutuelle says" text becomes a turn in the persona's
conversation script. The assertion becomes a rule-based check on the
agent's transcript + extracted data.
