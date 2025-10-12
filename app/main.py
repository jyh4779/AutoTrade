import os, json
from fastapi import FastAPI, Body
from pydantic import BaseModel
from .base_rules import rules_score, sl_tp_from_atr
from .openai_client import llm_adjust_and_explain
from .postproc import finalize

app = FastAPI(title="Codex Signal Scorer")

with open("prompts/signal_scorer.system.md", encoding="utf-8") as f:
    SYSTEM = f.read()
with open("prompts/signal_scorer.rubric.md", encoding="utf-8") as f:
    RUBRIC = f.read()
with open("prompts/output.schema.json", encoding="utf-8") as f:
    OUT_SCHEMA = f.read()

class Snapshot(BaseModel):
    symbol: str
    ts: str
    tf_min: int
    features: dict
    risk: dict | None = None

@app.post("/score")
def score_api(snap: Snapshot = Body(...)):
    base = rules_score(snap.features)
    sl, tp = sl_tp_from_atr(snap.features.get("atr_pct", 0.01))

    # LLM 보강
    llm = llm_adjust_and_explain(
        payload=json.loads(snap.model_dump_json()),
        base_score=base, system_prompt=SYSTEM, rubric=RUBRIC, out_schema=OUT_SCHEMA
    )

    # 기본 SL/TP가 없으면 채워줌
    llm.setdefault("sl_pct", sl)
    llm.setdefault("tp_pct", tp)
    llm.setdefault("holding_minutes", 6)

    return finalize(base, llm)
