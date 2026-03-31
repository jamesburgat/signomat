from __future__ import annotations

from pathlib import Path

import yaml

from signomat_pi.common.models import TaxonomyResult


class TaxonomyMapper:
    def __init__(self, config_path: Path):
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        self.version = str(payload.get("version", 1))
        self.rules = payload.get("rules", [])
        self.fallback = payload["defaults"]["fallback"]

    def map_label(self, raw_label: str) -> TaxonomyResult:
        for rule in self.rules:
            match = rule.get("match", {})
            if match.get("raw_label") == raw_label:
                return self._result_from_rule(raw_label, rule["output"])
            prefix = match.get("raw_label_prefix")
            if prefix and raw_label.startswith(prefix):
                return self._result_from_rule(raw_label, rule["output"])
        return TaxonomyResult(**self.fallback)

    def snapshot_entries(self) -> list[dict[str, str]]:
        entries = []
        for rule in self.rules:
            output = rule["output"]
            entries.append(
                {
                    "raw_label": rule["match"].get("raw_label") or rule["match"].get("raw_label_prefix", "*"),
                    "category_id": output["category_id"],
                    "category_label": output["category_label"],
                    "specific_label": output.get("specific_label")
                    or ("<raw>" if output.get("specific_label_from_raw") else output["category_id"]),
                    "grouping_mode": output["grouping_mode"],
                }
            )
        return entries

    def _result_from_rule(self, raw_label: str, output: dict[str, str]) -> TaxonomyResult:
        specific_label = raw_label if output.get("specific_label_from_raw") else output.get("specific_label", raw_label)
        return TaxonomyResult(
            category_id=output["category_id"],
            category_label=output["category_label"],
            specific_label=specific_label,
            grouping_mode=output["grouping_mode"],
        )

