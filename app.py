import os
import time
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── KIS API 설정 ────────────────────────────────────────────────
BASE_URL     = "https://openapi.koreainvestment.com:9443"
APP_KEY      = os.getenv("kis_app_key", "").strip()
APP_SECRET   = os.getenv("kis_app_secret", "").strip()
ACCOUNT_NO   = os.getenv("kis_account_no", "").strip()   # 계좌번호 (8자리)
ACCOUNT_CODE = os.getenv("kis_account_code", "").strip() # 상품코드 (예: 32)

# ── Supabase 설정 ────────────────────────────────────────────────
SUPABASE_URL = os.getenv("supabase_url", "").strip()
SUPABASE_KEY = os.getenv("supabase_service_key", "").strip()  # service_role key (쓰기용)

# ── Access Token 캐시 ───────────────────────────────────────────
_token_cache = {
    "access_token": None,
    "expires_at": 0,          # epoch seconds
}


def get_access_token() -> str:
    """Access Token을 발급하고 만료 전까지 캐싱한다 (유효기간 24h)."""
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    resp = requests.post(
        f"{BASE_URL}/oauth2/tokenP",
        headers={"Content-Type": "application/json"},
        json={
            "grant_type": "client_credentials",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"]   = now + int(data.get("expires_in", 86400))
    return _token_cache["access_token"]


def kis_headers(tr_id: str) -> dict:
    """KIS API 공통 헤더를 반환한다."""
    return {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey":        APP_KEY,
        "appsecret":     APP_SECRET,
        "tr_id":         tr_id,
    }


def _fetch_kis_stocks() -> tuple[dict, list]:
    """KIS API에서 전체 종목 목록(코드→이름)을 가져온다. (stocks, errors) 반환."""
    stocks: dict = {}
    errors: list = []

    # ① ETF 목록: CTPF1604R, PRDT_TYPE_CD=300
    try:
        resp = requests.get(
            f"{BASE_URL}/uapi/domestic-stock/v1/quotations/search-stock-info",
            headers=kis_headers("CTPF1604R"),
            params={"PRDT_TYPE_CD": "300", "PDNO": ""},
            timeout=10,
        )
        if resp.ok:
            out = resp.json().get("output", {})
            items = out if isinstance(out, list) else [out]
            for item in items:
                code = item.get("pdno", "").strip()
                name = item.get("prdt_name", "").strip()
                if code and name:
                    stocks[code] = name
    except Exception as e:
        errors.append(f"ETF 조회 실패: {e}")

    # ② 업종별 전종목: FHPST01710000 — KOSPI(J), KOSDAQ(Q)
    for market, upjong_cd in [("J", "0001"), ("Q", "Q001")]:
        try:
            resp = requests.get(
                f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-member",
                headers=kis_headers("FHPST01710000"),
                params={
                    "FID_COND_MRKT_DIV_CODE": market,
                    "FID_INPUT_ISCD": upjong_cd,
                },
                timeout=15,
            )
            if resp.ok:
                data = resp.json()
                if data.get("rt_cd") == "0":
                    for item in data.get("output", []):
                        code = item.get("mksc_shrn_iscd", "").strip()
                        name = item.get("hts_kor_isnm", "").strip()
                        if code and name:
                            stocks[code] = name
        except Exception as e:
            errors.append(f"{market} 시장 조회 실패: {e}")

    # ③ 결과가 없으면 단건이라도 확인
    if not stocks:
        try:
            resp = requests.get(
                f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=kis_headers("FHKST01010100"),
                params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": "005930"},
                timeout=5,
            )
            if resp.ok:
                name = resp.json().get("output", {}).get("hts_kor_isnm", "삼성전자").strip() or "삼성전자"
                stocks["005930"] = name
        except Exception:
            pass

    return stocks, errors


# ── /api/holdings  보유종목 조회 ────────────────────────────────
@app.route("/api/holdings")
def holdings():
    """보유 종목 잔고를 조회한다."""
    try:
        params = {
            "CANO":                  ACCOUNT_NO,
            "ACNT_PRDT_CD":          ACCOUNT_CODE,
            "AFHR_FLPR_YN":          "N",
            "OFL_YN":                "",
            "INQR_DVSN":             "01",
            "UNPR_DVSN":             "01",
            "FUND_STTL_ICLD_YN":     "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN":             "01",
            "CTX_AREA_FK100":        "",
            "CTX_AREA_NK100":        "",
        }
        resp = requests.get(
            f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=kis_headers("TTTC8434R"),
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            return jsonify({"error": data.get("msg1", "KIS API 오류")}), 502

        output1 = data.get("output1", [])
        output2 = data.get("output2", [{}])[0]

        holdings_list = [
            {
                "code":          item.get("pdno"),
                "name":          item.get("prdt_name"),
                "quantity":      int(item.get("hldg_qty", 0)),
                "avg_price":     float(item.get("pchs_avg_pric", 0)),
                "current_price": float(item.get("prpr", 0)),
                "eval_amount":   float(item.get("evlu_amt", 0)),
                "profit_loss":   float(item.get("evlu_pfls_amt", 0)),
                "profit_rate":   float(item.get("evlu_pfls_rt", 0)),
            }
            for item in output1
            if int(item.get("hldg_qty", 0)) > 0
        ]

        summary = {
            "total_eval":     float(output2.get("tot_evlu_amt", 0)),
            "total_purchase": float(output2.get("pchs_amt_smtl_amt", 0)),
            "total_profit":   float(output2.get("evlu_pfls_smtl_amt", 0)),
            "deposit":        float(output2.get("dnca_tot_amt", 0)),
        }

        return jsonify({"holdings": holdings_list, "summary": summary})

    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /api/price  현재가 조회 ─────────────────────────────────────
@app.route("/api/price")
def price():
    """단일 종목 현재가를 조회한다. ?code=005930 형식으로 호출."""
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"error": "code 파라미터가 필요합니다"}), 400

    try:
        resp = requests.get(
            f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=kis_headers("FHKST01010100"),
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD":         code,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("rt_cd") != "0":
            return jsonify({"error": data.get("msg1", "KIS API 오류")}), 502

        output = data.get("output", {})

        # hts_kor_isnm은 ETF 조회 시 KIS가 빈값으로 반환 → search-stock-info로 fallback
        name = output.get("hts_kor_isnm", "").strip()
        if not name:
            try:
                info_resp = requests.get(
                    f"{BASE_URL}/uapi/domestic-stock/v1/quotations/search-stock-info",
                    headers=kis_headers("CTPF1604R"),
                    params={"PRDT_TYPE_CD": "300", "PDNO": code},
                    timeout=5,
                )
                info_out = info_resp.json().get("output", {})
                name = info_out.get("prdt_name", "").strip()
            except Exception:
                pass

        return jsonify({
            "code":          code,
            "name":          name,
            "current_price": int(output.get("stck_prpr", 0)),
            "open_price":    int(output.get("stck_oprc", 0)),
            "high_price":    int(output.get("stck_hgpr", 0)),
            "low_price":     int(output.get("stck_lwpr", 0)),
            "change":        int(output.get("prdy_vrss", 0)),
            "change_rate":   float(output.get("prdy_ctrt", 0)),
            "volume":        int(output.get("acml_vol", 0)),
        })

    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /api/stock-list  전체 종목 목록 (로컬용) ────────────────────
@app.route("/api/stock-list")
def stock_list():
    """KIS API에서 종목 목록을 가져와 반환한다. (Supabase 미설정 시 로컬 대체용)"""
    stocks, errors = _fetch_kis_stocks()
    return jsonify({"stocks": stocks, "count": len(stocks), "errors": errors})


# ── /api/sync-stocks  KIS → Supabase 동기화 ─────────────────────
@app.route("/api/sync-stocks")
def sync_stocks():
    """KIS 종목 목록을 가져와 Supabase에 upsert한다."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return jsonify({
            "error": ".env에 supabase_url, supabase_service_key를 설정해주세요",
        }), 400

    stocks, kis_errors = _fetch_kis_stocks()
    if not stocks:
        return jsonify({"error": "KIS에서 종목을 가져오지 못했습니다", "details": kis_errors}), 502

    rows = [{"code": k, "name": v} for k, v in stocks.items()]
    synced = 0
    sb_errors = []
    batch_size = 500

    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            resp = requests.post(
                f"{SUPABASE_URL}/rest/v1/stocks",
                headers={
                    "apikey":        SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type":  "application/json",
                    "Prefer":        "resolution=merge-duplicates",
                },
                json=batch,
                timeout=30,
            )
            resp.raise_for_status()
            synced += len(batch)
        except Exception as e:
            sb_errors.append(str(e))

    return jsonify({
        "synced":  synced,
        "total":   len(rows),
        "errors":  sb_errors + kis_errors,
    })


# ── /api/claude  Anthropic 프록시 ───────────────────────────────
@app.route("/api/claude", methods=["POST"])
def claude_proxy():
    """브라우저 대신 서버에서 Anthropic API를 호출한다. (.env의 키 사용)"""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key or api_key.startswith("여기에"):
        return jsonify({"error": "ANTHROPIC_API_KEY가 .env에 설정되지 않았습니다."}), 400

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "요청 본문이 없습니다."}), 400

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json=payload,
            timeout=120,
        )
        return resp.content, resp.status_code, {"Content-Type": "application/json"}
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


# ── 헬스체크 ────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
