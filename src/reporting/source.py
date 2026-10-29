"""Validate completeness and redact credentials without changing engineering numbers."""

from copy import deepcopy
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import re

from src.models import Handoff
from src.models.contracts import ORDER


class PackageError(ValueError):
    code = "document_generation_failed"


SECRET_KEYS = {"apikey", "openaiapikey", "secrets", "api_key", "openai_api_key", "password", "passwd", "authorization", "access_token",
               "refresh_token", "client_secret", "private_key", "credentials", "secret"}


def redact(value):
    if isinstance(value, dict):
        return {k: "[ODSTRANJENO]" if k.lower().replace("-", "_") in SECRET_KEYS else redact(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[ODSTRANJENO]", value)
        value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [ODSTRANJENO]", value)
        return re.sub(r"(?i)\b(password|api[_-]?key|client_secret)\s*[:=]\s*[^\s,;]+", r"\1=[ODSTRANJENO]", value)
    return value


def prepare(document, metadata=None):
    if not isinstance(document,dict):
        raise PackageError("Izvor mora biti strukturiran JSON objekt.")
    clean = redact(deepcopy(document))
    if clean.get("engineering_verified") is True:
        raise PackageError("Ta izobraževalni paket ne potrjuje konstrukcije.")
    if clean.get("format") == "razvojni-paket-v1" and (not isinstance(clean.get("execution"),dict) or clean["execution"].get("status") != "awaiting_approval"):
        raise PackageError("Izvorni paket ne potrjuje uspešnega programskega cikla.")
    if "status" in clean and clean["status"] != "awaiting_approval":
        raise PackageError("Razvojni cikel ni uspešno zaključen; celoten paket ni dovoljen.")
    raw = clean.get("handoff", clean)
    if not isinstance(raw,dict):
        raise PackageError("Manjka strukturirana predaja.")
    try:
        handoff = Handoff(**{f.name: raw[f.name] for f in fields(Handoff) if f.name in raw})
        if handoff.inputs.get("data_origin") != "synthetic" or tuple(handoff.results) != ORDER:
            raise ValueError("incomplete")
        for name in ORDER:
            data = handoff.results[name]
            engineering = data["engineering"]
            if data["engineering_verified"] is not False or engineering["engineering_verified"] is not False:
                raise ValueError("approval")
            if data.get("variant", handoff.variant) != handoff.variant or data.get("revision", handoff.revision) != handoff.revision:
                raise ValueError("identity")
        c = handoff.results["konstruktor"]["engineering"]
        h = handoff.results["hidravlik"]["engineering"]
        e = handoff.results["ekonomist"]["engineering"]
        r = handoff.results["recenzent"]["engineering"]
        if (len(c["positions"]) != 11 or len(h["force_curve"]) != 11
                or [p["pressure_bar"] for p in h["pressure_options"]] != [160, 200, 250, 315]
                or not r["checks"] or r["calculation_check_passed"] is not True
                or handoff.results["recenzent"]["decision"] != "changes_required"
                or r["status"] != "changes_required"):
            raise ValueError("validation")
        if c["units"]["length"] != "mm" or c["units"]["force"] != "N" or h["units"]["pressure"] != "bar":
            raise ValueError("units")
        # Verify provenance, not a new design or recomputed engineering variant.
        from src.models.contracts import digest
        if h["source_constructor_sha256"] != digest(c) or e["source_constructor_sha256"] != digest(c) or e["source_hydraulics_sha256"] != digest(h):
            raise ValueError("provenance")
        if e["verified_prices"] or e["total_EUR"] is not None:
            raise ValueError("prices")
        from src.engineering.costs import allowed_cost_items, cost_issues
        if cost_issues(e["cost_items"], allowed_cost_items(c["parameters"]["arm_length_mm"])):
            raise ValueError("catalogue")
        if any(check["status"] != "pass" for check in r["checks"]):
            raise ValueError("checks")
        for row, curve in zip(c["positions"], h["force_curve"]):
            if any(row[k] != curve[v] for k,v in (("platform_height_mm","platform_height_mm"), ("cylinder_length_mm","cylinder_length_mm"), ("cylinder_force_N","force_N"))):
                raise ValueError("handoff")
        for item in e["cost_items"]:
            if item["price_kind"] not in ("synthetic", "unknown") or ((item["amount_EUR"] is None) != (item["price_kind"] == "unknown")):
                raise ValueError("costs")
    except (KeyError, TypeError, ValueError) as exc:
        raise PackageError("Neveljavna, nepopolna ali tehnično nasprotujoča predaja; paket ni ustvarjen.") from None
    inherited = clean.get("provenance", {}) if clean.get("format") == "razvojni-paket-v1" else {}
    if not isinstance(inherited,dict) or metadata is not None and not isinstance(metadata,dict):
        raise PackageError("Neveljavni podatki o sledljivosti.")
    metadata = redact({**deepcopy(inherited), **deepcopy(metadata or {})})
    for key in ("report", "cycle_record"):
        if key in metadata and (not isinstance(metadata[key],dict) or metadata[key].get("status") != "awaiting_approval"):
            raise PackageError("Izvorni dnevnik ne potrjuje zaključenega cikla.")
    if "cycle_record" in metadata and metadata["cycle_record"]["handoff"] != handoff.to_dict():
        raise PackageError("Rezultat in izvorni dnevnik se ne ujemata.")
    return handoff, {"format": "razvojni-paket-v1", "handoff": handoff.to_dict(),
                     "generator": {"commit": os.environ.get("GITHUB_SHA", "local"),
                                   "run_id": os.environ.get("GITHUB_RUN_ID", "local"), "model_calls_for_documents": 0},
                     "execution": clean["execution"] if clean.get("format") == "razvojni-paket-v1" else {k: v for k, v in clean.items() if k != "handoff"} if "handoff" in clean else {"status": "awaiting_approval", "basis": "Štiri zaključene strukturirane predaje in ohranjena validacija."},
                     "provenance": metadata, "engineering_verified": False,
                     "technical_status": "changes_required", "data_policy": "Sintetični podatki; poverilnice so odstranjene."}


def load(path, metadata_dir=None):
    path = Path(path)
    raw = path.read_bytes()
    metadata = {"input_file": path.name, "input_file_sha256": hashlib.sha256(raw).hexdigest()}
    parsed = json.loads(raw)
    if not isinstance(parsed,dict):
        raise PackageError("Izvor mora biti JSON objekt.")
    body = parsed.get("handoff", parsed)
    if not isinstance(body,dict):
        raise PackageError("Manjka strukturirana predaja.")
    variant, revision = body.get("variant", ""), body.get("revision", "")
    if not isinstance(variant,str) or not isinstance(revision,str) or not re.fullmatch(r"V[0-9]{2,}",variant) or not re.fullmatch(r"R[0-9]{2,}",revision):
        raise PackageError("Manjka veljavna identiteta variante in revizije.")
    if metadata_dir:
        root = Path(metadata_dir)
        for key, filename in (("manifest", "manifest.json"), ("report", "report.json"), ("cycle_record", f"runs/{variant}-{revision}.json")):
            file = root / filename
            if file.exists():
                metadata[key] = json.loads(file.read_text(encoding="utf-8"))
    return parsed, metadata
