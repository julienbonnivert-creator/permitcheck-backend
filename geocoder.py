"""
Geocoding: address -> Lambert 72 (x, y) coordinates

Primary:  SPW ICAR_ADR_PT service (WalOnMap)
Fallback: User-supplied coordinates
"""

import httpx
import re
from typing import Optional


ICAR_BASE = (
    "https://geoservices.wallonie.be/arcgis/rest/services"
    "/DONNEES_BASE/ICAR_ADR_PT/MapServer"
)


def _clean(s: str) -> str:
    return s.strip().upper()


async def geocode_address(
    rue: str,
    numero: str,
    commune: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict]:
    """
    Find coordinates (Lambert 72) for a Walloon address.

    Returns: {"x": float, "y": float, "label": str} or None
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        # Strategy 1: search address points (layer 1) by commune + rue + numero
        where = (
            f"LOCALITE LIKE '%{_clean(commune)}%'"
            f" AND NOM_RUE_FR LIKE '%{_clean(rue)}%'"
        )
        if numero:
            where += f" AND NUM_ORDRE = '{numero.strip()}'"

        params = {
            "where": where,
            "outFields": "NOM_RUE_FR,LOCALITE,NUM_ORDRE",
            "returnGeometry": "true",
            "outSR": "31370",
            "f": "json",
            "resultRecordCount": 1,
        }

        resp = await client.get(
            f"{ICAR_BASE}/1/query", params=params, timeout=10.0
        )
        data = resp.json()
        features = data.get("features", [])

        if features:
            geom = features[0].get("geometry", {})
            attr = features[0].get("attributes", {})
            if geom.get("x") and geom.get("y"):
                label = (
                    f"{attr.get('NOM_RUE_FR','')} {attr.get('NUM_ORDRE','')}, "
                    f"{attr.get('LOCALITE','')}"
                ).strip(", ")
                return {"x": geom["x"], "y": geom["y"], "label": label}

        # Strategy 2: relax — search only by commune + rue (no number)
        where2 = (
            f"LOCALITE LIKE '%{_clean(commune)}%'"
            f" AND NOM_RUE_FR LIKE '%{_clean(rue)}%'"
        )
        params2 = {
            "where": where2,
            "outFields": "NOM_RUE_FR,LOCALITE",
            "returnGeometry": "true",
            "outSR": "31370",
            "f": "json",
            "resultRecordCount": 1,
        }
        resp2 = await client.get(
            f"{ICAR_BASE}/1/query", params=params2, timeout=10.0
        )
        data2 = resp2.json()
        features2 = data2.get("features", [])

        if features2:
            geom2 = features2[0].get("geometry", {})
            attr2 = features2[0].get("attributes", {})
            if geom2.get("x") and geom2.get("y"):
                label2 = (
                    f"{attr2.get('NOM_RUE_FR','')} {numero}, "
                    f"{attr2.get('LOCALITE','')}"
                ).strip(", ")
                return {
                    "x": geom2["x"],
                    "y": geom2["y"],
                    "label": label2,
                    "approximate": True,
                }

        return None

    except Exception:
        return None

    finally:
        if own_client:
            await client.aclose()
