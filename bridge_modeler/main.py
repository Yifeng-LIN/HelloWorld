from __future__ import annotations
from typing import Any
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from bridge_modeler.parsers.image_parser import parse_image
from bridge_modeler.parsers.params_parser import parse_params
from bridge_modeler.parsers.dialog_parser import parse_dialog, DialogResponse
from bridge_modeler.engine.ifc_exporter import export_to_ifc
from bridge_modeler.models.irg import ValidationResult

app = FastAPI(title="BridgeModeler SaaS", version="1.0.0")


class ParseResponse(BaseModel):
    validation: ValidationResult
    ifc_path: str | None = None


class DialogRequest(BaseModel):
    message: str
    history: list[dict[str, Any]] = []


class DialogParseResponse(BaseModel):
    validation: ValidationResult
    ifc_path: str | None = None
    follow_up_question: str | None = None


def _maybe_export(result: ValidationResult) -> str | None:
    if result.passed and result.irg:
        return export_to_ifc(result.irg)
    return None


@app.post("/parse/image", response_model=ParseResponse)
async def parse_image_endpoint(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    result = parse_image(data)
    return ParseResponse(validation=result, ifc_path=_maybe_export(result))


@app.post("/parse/params", response_model=ParseResponse)
async def parse_params_endpoint(body: dict[str, Any]):
    result = parse_params(body)
    return ParseResponse(validation=result, ifc_path=_maybe_export(result))


@app.post("/parse/dialog", response_model=DialogParseResponse)
async def parse_dialog_endpoint(body: DialogRequest):
    resp: DialogResponse = parse_dialog(body.message, body.history)
    ifc_path = _maybe_export(resp.validation)
    return DialogParseResponse(
        validation=resp.validation,
        ifc_path=ifc_path,
        follow_up_question=resp.follow_up_question,
    )


@app.get("/health")
def health():
    return {"status": "ok"}
