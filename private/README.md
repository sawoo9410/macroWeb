# private/ — git 제외 (README와 .env.example만 추적)

- `.env` : API 키·토큰. `cp env.example .env` 후 값 입력. **Claude 세션은 이 파일을 읽지도 출력하지도 않는다.**
- `portfolio.yaml` : 포트폴리오 렌즈 입력(Phase 5). 수량·금액은 리포트에 쓰지 않고 비중·노출 방향만 쓴다.
