---
id: oil
type: asset
status: candidate
aliases: ["Brent"]
n_stories: 0
conflict_of_interest: False
---
# Brent

- data_key: FRED:DCOILBRENTEU

## 관계 (나가는 엣지)
- pressures → [[fed]] (sign +, w 0.40 × c 0.50, evidence 0, candidate)

## 관계 (들어오는 엣지)
- triggers ← [[iran-conflict]] (sign +, w 0.70 × c 0.50, evidence 0, candidate)

## 주요 claim

> 생성: macroweb graph export-vault · 2026-11-03T14:07+00:00