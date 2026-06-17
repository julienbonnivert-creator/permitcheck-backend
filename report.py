"""
Rapport IA — appel Claude API avec les donnees WalOnMap structurees
"""

import json
import os
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

DISCLAIMER = (
    "CE RAPPORT EST FOURNI A TITRE INFORMATIF UNIQUEMENT. "
    "Il ne constitue pas un avis juridique, urbanistique ou environnemental. "
    "Les donnees proviennent de sources publiques wallonnes (WalOnMap, BDES) et "
    "peuvent etre incompletes ou outdatees. Ce rapport n'engage pas la responsabilite "
    "de son auteur. Consultez toujours un architecte agree et l'administration communale "
    "avant tout acte juridique ou de construction."
)

SYSTEM_PROMPT = """Tu es un assistant expert en urbanisme wallon. Tu analyses les donnees
geographiques d'une parcelle wallonne et tu generes un rapport de pre-faisabilite en francais.

Tu connais parfaitement :
- Le CoDT (Code du Developpement Territorial) wallon
- Le Plan de Secteur wallon et ses zones d'affectation
- Le Decret Sols wallon et la BDES
- Les risques naturels wallons (karst, inondations, glissements)
- Les contraintes environnementales (captages, Natura 2000)

Ton rapport doit etre structure, clair, et indiquer clairement le niveau de risque
(VERT / ORANGE / ROUGE) pour chaque thematique. Il doit terminer par une synthese
des points de vigilance et des etudes complementaires recommandees.

Tu DOIS toujours inclure le disclaimer suivant en debut de rapport :
"RAPPORT INFORMATIF — Ce document ne constitue pas un avis professionnel engage."
"""


def _summarize_layers(layers: dict) -> str:
    """Convert raw layer data to a readable summary for the AI prompt."""
    lines = []

    # Plan de secteur
    ps = layers.get("plan_secteur", {})
    if ps.get("features"):
        f = ps["features"][0]
        lines.append(
            f"PLAN DE SECTEUR: Zone '{f.get('DESCRIPTION', 'inconnue')}' "
            f"(code {f.get('AFFECT', '?')}, article CoDT: {f.get('ART_CODT', '?')})"
        )
    else:
        lines.append("PLAN DE SECTEUR: Aucune zone identifiee (parcelle hors plan?)")

    # BDES
    bdes_obl = layers.get("bdes_obligatoire", {})
    bdes_ind = layers.get("bdes_indicatif", {})
    n_obl = bdes_obl.get("count", 0)
    n_ind = bdes_ind.get("count", 0)
    if n_obl > 0:
        lines.append(f"BDES (obligations): {n_obl} parcelle(s) avec demarches obligatoires (Art. 12 S2/3 Decret Sols)")
    elif n_ind > 0:
        lines.append(f"BDES (indicatif): {n_ind} parcelle(s) avec informations indicatives (Art. 12 S4)")
    else:
        lines.append("BDES: Aucune inscription en base de donnees des sols pollues")

    # Karst
    karst = layers.get("karst", {})
    if karst.get("count", 0) > 0:
        types = list({f.get("PHENO_DESC", "?") for f in karst.get("features", [])})
        noms = [f.get("DENOM", "") for f in karst.get("features", [])][:3]
        lines.append(
            f"KARST: {karst['count']} phenomene(s) dans rayon 500m — "
            f"types: {', '.join(types)} — sites: {', '.join(noms)}"
        )
    else:
        lines.append("KARST: Aucun phenomene karstique recense dans rayon 500m")

    # Mines
    mines = layers.get("concessions_mines", {})
    if mines.get("count", 0) > 0:
        noms_m = [f.get("NOM", "?") for f in mines.get("features", [])][:3]
        lines.append(f"MINES: {mines['count']} concession(s) dans rayon 1km — {', '.join(noms_m)}")
    else:
        lines.append("MINES: Aucune concession miniere dans rayon 1km")

    # Terrils
    terrils = layers.get("terrils", {})
    if terrils.get("count", 0) > 0:
        lines.append(f"TERRILS: {terrils['count']} terril(s) dans rayon 500m")
    else:
        lines.append("TERRILS: Aucun terril recense dans rayon 500m")

    # Inondation
    inond = layers.get("alea_inondation", {})
    zi = layers.get("zones_inondees", {})
    if inond.get("count", 0) > 0:
        vals = [f.get("VALEUR", "?") for f in inond.get("features", [])]
        lines.append(f"ALEA INONDATION: Parcelle en zone d'alea '{', '.join(vals)}'")
    elif zi.get("count", 0) > 0:
        lines.append("INONDATION: Parcelle en zone historiquement inondee")
    else:
        lines.append("INONDATION: Aucun alea d'inondation recense sur la parcelle")

    # Captages
    capt = layers.get("protection_captages", {})
    if capt.get("count", 0) > 0:
        types_c = [f.get("TYPE_ZONE", "?") for f in capt.get("features", [])][:2]
        lines.append(f"CAPTAGES EAU: Parcelle en zone de protection ({', '.join(types_c)})")
    else:
        lines.append("CAPTAGES EAU: Hors zone de protection de captage")

    # Contraintes karst
    ck = layers.get("contraintes_karst", {})
    if ck.get("count", 0) > 0:
        lines.append(f"CONTRAINTES KARST (urbanisme): {ck['count']} contrainte(s) applicables")
    else:
        lines.append("CONTRAINTES KARST: Aucune contrainte urbanistique karstique")

    # Risque eboulement
    reb = layers.get("risque_eboulement", {})
    if reb.get("count", 0) > 0:
        lines.append(f"RISQUE EBOULEMENT/GLISSEMENT: {reb['count']} zone(s) a risque identifiees")
    else:
        lines.append("RISQUE EBOULEMENT: Aucun risque recense")

    # SAR
    sar = layers.get("sites_reamenager", {})
    if sar.get("count", 0) > 0:
        noms_s = [f.get("NOM", "?") for f in sar.get("features", [])][:2]
        lines.append(f"SAR: Proximite d'un site a reamenager ({', '.join(noms_s)})")
    else:
        lines.append("SAR: Aucun site a reamenager dans le perimetre")

    return "\n".join(lines)


async def generate_report(
    address_label: str,
    project_description: str,
    layers: dict,
    commune: str = "",
) -> dict:
    """Call Claude API and return structured report."""

    data_summary = _summarize_layers(layers)

    user_prompt = f"""Adresse analysee: {address_label}
Commune: {commune}
Description du projet: {project_description}

DONNEES WALONMAP RECUEILLIES:
{data_summary}

Genere un rapport de pre-faisabilite urbanistique complet avec:
1. En-tete (adresse, date, disclaimer)
2. ZONAGE - Plan de secteur: zone applicable, implications CoDT, actes/travaux autorises/interdits
3. POLLUTION DES SOLS (BDES): statut, implications Decret Sols, obligations eventuelles
4. RISQUES GEOTECHNIQUES: karst, mines, terrils, eboulements — niveau de risque et recommandations
5. RISQUES HYDROLOGIQUES: inondation, ruissellement — niveau de risque et prescriptions
6. CONTRAINTES ENVIRONNEMENTALES: captages, Natura 2000 si applicable
7. FAISABILITE DU PROJET: evaluation globale (FAVORABLE / SOUS CONDITIONS / COMPLEXE / DEFAVORABLE)
8. ETUDES COMPLEMENTAIRES RECOMMANDEES: liste prioritisee
9. NEXT STEPS: 3 actions concretes a realiser en priorite

Pour chaque section, indique clairement: VERT (pas de contrainte), ORANGE (contrainte moderee), ROUGE (contrainte majeure).
"""

    message = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    report_text = message.content[0].text

    return {
        "disclaimer": DISCLAIMER,
        "address": address_label,
        "commune": commune,
        "project": project_description,
        "data_layers": _summarize_layers(layers),
        "report": report_text,
        "model": message.model,
        "usage": {
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        },
    }
