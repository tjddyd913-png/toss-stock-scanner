# toss-stock-scanner v2

Render 설정
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Root Directory: 비워두기

v2 변경점
- 당일 누적 거래량
- 최근 거래일 평균 거래량 기반 RVOL
- 당일 분봉 VWAP
- 조건별 통과/미달 표시
- 업데이트 시각 표시
