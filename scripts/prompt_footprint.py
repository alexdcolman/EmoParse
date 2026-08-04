"""Mide el tamaño de los system prompts renderizados más sensibles."""

from __future__ import annotations

import math
from pathlib import Path

import yaml

from emoparse.core.prompts import characterizer, emotions
from emoparse.knowledge.loader import KnowledgeLoader


def build_footprint(root: Path) -> dict[str, int]:
    knowledge = KnowledgeLoader(root / "knowledge")
    configurations = knowledge.load_emotion_configurations("configuraciones_emocion.json")
    modes = knowledge.load_ontology("emociones.json")
    emotion_heuristics = "\n\n".join(
        [
            knowledge.load_heuristics("heuristicas/emotions.md"),
            knowledge.load_heuristics("heuristicas/emotions_tuit.md"),
        ]
    )
    emotion_prompt = emotions.render_system(
        configuraciones=configurations,
        titulo="",
        tipo_discurso="tuit",
        enunciador="@autor.bsky.social",
        heuristicas=emotion_heuristics,
        modos_existencia=modes,
        template="emotions_system_tuit",
    )
    characterizer_prompt = characterizer.render_system(
        titulo="",
        tipo_discurso="tuit",
        enunciador="@autor.bsky.social",
        heuristicas=knowledge.load_heuristics("heuristicas/characterizer.md"),
    )
    return {
        "emotions_tuit_system_chars": len(emotion_prompt),
        "characterizer_system_chars": len(characterizer_prompt),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    budget = yaml.safe_load(
        (root / "evals/prompt_regression/prompt_budget.yaml").read_text(encoding="utf-8")
    )
    chars_per_token = int(budget["assumed_chars_per_token"])
    limits = budget["limits"]
    reference = budget.get("reference", {})
    gemma = budget.get("gemma4_31b", {})
    footprint = build_footprint(root)

    failed = False
    for name, chars in footprint.items():
        estimated_tokens = math.ceil(chars / chars_per_token)
        limit = int(limits[name])
        status = "OK" if chars <= limit else "EXCEDE"
        print(
            f"{name}: {chars} chars (~{estimated_tokens} tokens) "
            f"/ tope de regresión {limit} [{status}]"
        )
        failed = failed or chars > limit

        fix08 = reference.get("fix_val01_08", {}).get(name)
        if fix08 is not None:
            delta = chars - int(fix08)
            percent = (delta / int(fix08)) * 100
            print(f"  vs FIX-VAL01-08: {delta:+d} chars ({percent:+.1f}%)")

    context_length = int(gemma.get("context_length", 0) or 0)
    if context_length:
        emotions_tokens = math.ceil(footprint["emotions_tuit_system_chars"] / chars_per_token)
        if emotions_tokens >= context_length:
            print(
                "ADVERTENCIA GEMMA4: la estimación conservadora del system "
                "prompt alcanza o supera context_length=4096. "
                "El tokenizer real y el corpus largo deben probarse."
            )
        else:
            remaining = context_length - emotions_tokens
            print(
                "Margen estimado Gemma4 antes de user prompt y salida: "
                f"~{remaining} tokens. Esta cifra no reemplaza la prueba real."
            )

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
