"""
WalOnMap layer queries — geoservices.wallonie.be ArcGIS REST API
All coordinates must be in Lambert 72 (EPSG:31370)
"""

import asyncio
import httpx
from typing import Any

BASE = "https://geoservices.wallonie.be/arcgis/rest/services"

LAYERS = {
    "plan_secteur": f"{BASE}/AMENAGEMENT_TERRITOIRE/PDS/MapServer/22/query",
    "bdes_obligatoire": f"{BASE}/SOL_SOUS_SOL/BDES_INVENTAIRE/MapServer/0/query",
    "bdes_indicatif": f"{BASE}/SOL_SOUS_SOL/BDES_INVENTAIRE/MapServer/1/query",
    "karst": f"{BASE}/SOL_SOUS_SOL/KARST/MapServer/0/query",
    "concessions_mines": f"{BASE}/SOL_SOUS_SOL/CONCESSIONS_MINES_SITUATION_ADMIN/MapServer/0/query",
    "terrils": f"{BASE}/SOL_SOUS_SOL/TERRILS_2018/MapServer/0/query",
    "alea_inondation": f"{BASE}/EAU/ALEA_INOND/MapServer/2/query",
    "zones_inondees": f"{BASE}/EAU/ZONES_INONDEES/MapServer/0/query",
    "protection_captages": f"{BASE}/EAU/PROTECT_CAPT/MapServer/0/query",
    "contraintes_karst": f"{BASE}/AMENAGEMENT_TERRITOIRE/CONTR_KARST/MapServer/0/query",
    "risque_eboulement": f"{BASE}/AMENAGEMENT_TERRITOIRE/RISQ_EBOULT/MapServer/0/query",
    "sites_reamenager": f"{BASE}/AMENAGEMENT_TERRITOIRE/SAR/MapServer/0/query",
}

POINT_FIELDS = {
    "plan_secteur": "AFFECT,DESCRIPTION,ART_CODT",
    "bdes_obligatoire": "*",
    "bdes_indicatif": "*",
    "karst": "PHENO_DESC,DENOM,COMMUNE,DESCRIPTION",
    "concessions_mines": "NOM,SUBSTANCE,STATUT",
    "terrils": "NOM,COMMUNE,SURFACE_HA",
    "alea_inondation": "TYPEALEA,VALEUR,CODEALEA",
    "zones_inondees": "*",
    "protection_captages": "NOM,TYPE_ZONE,CAPTAGE",
    "contraintes_karst": "*",
    "risque_eboulement": "*",
    "sites_reamenager": "NOM,COMMUNE,STATUT,SUPERFICIE",
}

# Radius (metres) for point-proximity searches
BUFFER_RADIUS = {
    "karst": 500,
    "concessions_mines": 1000,
    "terrils": 500,
    "sites_reamenager": 200,
}


async def query_layer(
    client: httpx.AsyncClient,
    name: str,
    url: str,
    x: float,
    y: float,
) -> dict[str, Any]:
    """Query a single WalOnMap layer and return structured result."""
    radius = BUFFER_RADIUS.get(name)

    params: dict[str, Any] = {
        "geometry": f"{x},{y}",
        "geometryType": "esriGeometryPoint",
        "inSR": "31370",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": POINT_FIELDS.get(name, "*"),
        "f": "json",
        "resultRecordCount": 10,
    }

    if radius:
        params["distance"] = radius
        params["units"] = "esriSRUnit_Meter"

    try:
        resp = await client.get(url, params=params, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            return {"layer": name, "status": "error", "message": data["error"].get("message", "unknown")}

        features = data.get("features", [])
        return {
            "layer": name,
            "status": "ok",
            "count": len(features),
            "features": [f["attributes"] for f in features],
        }

    except Exception as exc:
        return {"layer": name, "status": "error", "message": str(exc)}


async def query_all_layers(x: float, y: float) -> dict[str, Any]:
    """Query all WalOnMap layers concurrently and return combined results."""
    async with httpx.AsyncClient() as client:
        tasks = [
            query_layer(client, name, url, x, y)
            for name, url in LAYERS.items()
        ]
        results = await asyncio.gather(*tasks)

    return {r["layer"]: r for r in results}
