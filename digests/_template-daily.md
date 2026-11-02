# 일일 다이제스트 {{date}} (KST) — 10줄

1. **레짐 한 줄**: {{regime_line}}
2. **T0 1차 문서**: {{t0_docs}}  ← 성명·공시·통계 원문 {{n_t0}}건, diff 처리 {{n_diff}}건
3. **고영향 claim 1**: {{claim_1}} [{{claim_1_label}} · {{claim_1_id}}]
4. **고영향 claim 2**: {{claim_2}} [{{claim_2_label}} · {{claim_2_id}}]
5. **고영향 claim 3**: {{claim_3}} [{{claim_3_label}} · {{claim_3_id}}]
6. **시장 정합성**: {{market_consistency}}  (전파 부호 ≠ 가격 반응이면 여기)
7. **검증 큐**: 고영향·저신뢰 {{n_review}}건 → review/{{date}}.md
8. **걸러낸 것**: {{filtered}}  (DEBUNKED/RECYCLED/SPAM {{n_filtered}}건)
9. **수집 상태**: 기사 {{n_articles}} · Story {{n_stories}} · degraded {{degraded}} · 비용 ${{cost_today}} (월 {{cost_pct}}%)
10. **내일 볼 것**: {{tomorrow}}

> [F]=검증 사실 [I]=해석 [S]=추측 · 매수·매도 지시 없음 · 생성: `uv run macroweb digest --date {{date}}`
