# migrations/

`schema.sql`은 v1 전체 DDL이다. v2부터는 `NNNN_<설명>.sql`(예: `0002_add_claim_lang.sql`)을 추가하고 ADR을 남긴다.
`macroweb db init`이 `schema_version` 보다 큰 번호의 파일을 순서대로 적용한다. 적용된 파일은 수정하지 않는다.
