"""
PermitCheck Wallonie — Backend API
Analyse urbanistique et environnementale automatisee pour la Wallonie

Usage:
  POST /analyze          — analyse complete (geocodage + couches + rapport IA)
  GET  /layers           — donnees brutes WalOnMap uniquement (sans rapport)
  GET  /health           — statut du service

Deploiement: Railway / Render / Fly.io
"""

import os
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from geocoder import geocode_address
from walonmap import query_all_layers
from report import generate_report

app = FastAPI(
    title="PermitCheck Wallonie",
    description="Analyse de pre-faisabilite urbanistique en Wallonie",
    version="1.0.0",
)

# CORS — autorise tous les domaines (Base44, front-end, etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ─── Schemas ──────────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    rue: str                          # Ex: "Rue de la Loi"
    numero: str = ""                  # Ex: "16"
    commune: str                      # Ex: "Namur"
    project: str = "Projet non specifie"  # Description du projet
    # Optionnel : coordonnees Lambert 72 si geocodage echoue
    x_lb72: Optional[float] = None
    y_lb72: Optional[float] = None


class LayersRequest(BaseModel):
    x_lb72: float
    y_lb72: float


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "PermitCheck Wallonie",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@app.post("/layers")
async def get_layers(req: LayersRequest):
    """Retourne les donnees brutes de toutes les couches WalOnMap."""
    layers = await query_all_layers(req.x_lb72, req.y_lb72)
    return {
        "x": req.x_lb72,
        "y": req.y_lb72,
        "layers": layers,
    }


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    """
    Analyse complete :
    1. Geocodage de l'adresse
    2. Interrogation de toutes les couches WalOnMap
    3. Generation du rapport par Claude
    """

    # 1. Geocodage
    coords = None
    address_label = f"{req.rue} {req.numero}, {req.commune}".strip()

    if req.x_lb72 and req.y_lb72:
        # Coordonnees fournies directement
        coords = {"x": req.x_lb72, "y": req.y_lb72, "label": address_label}
    else:
        coords = await geocode_address(req.rue, req.numero, req.commune)

    if not coords:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Impossible de geocoder l'adresse '{address_label}'. "
                "Verifiez l'orthographe ou fournissez des coordonnees Lambert 72 "
                "via les champs x_lb72 et y_lb72."
            ),
        )

    x, y = coords["x"], coords["y"]
    label = coords.get("label", address_label)
    approximate = coords.get("approximate", False)

    # 2. Couches WalOnMap (toutes en parallele)
    layers = await query_all_layers(x, y)

    # 3. Rapport IA
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # Mode demo sans cle API — retourne les donnees brutes
        return {
            "geocoding": {"x": x, "y": y, "label": label, "approximate": approximate},
            "layers": layers,
            "report": "[DEMO] Configurez ANTHROPIC_API_KEY pour generer le rapport IA.",
        }

    report = await generate_report(
        address_label=label,
        project_description=req.project,
        layers=layers,
        commune=req.commune,
    )

    return {
        "geocoding": {
            "x": x,
            "y": y,
            "label": label,
            "approximate": approximate,
        },
        "layers_summary": report["data_layers"],
        "report": report["report"],
        "disclaimer": report["disclaimer"],
        "meta": {
            "model": report["model"],
            "tokens": report["usage"],
            "generated_at": datetime.utcnow().isoformat(),
        },
    }


# ─── Dev server ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
