import html
import re
from datetime import date, timedelta
from urllib.parse import urljoin

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ============================================================
# Naver Securities Research Viewer
# New Naver Stock (stock.naver.com) / Next.js 대응
# API 우선 + HTML fallback
# ============================================================

BASE_URL = "https://stock.naver.com"
RESEARCH_URL = f"{BASE_URL}/research/company"
API_BASE = f"{BASE_URL}/api/stockSecurity/researches/v2"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": RESEARCH_URL,
}

session = requests.Session()
session.headers.update(HEADERS)


# -----------------------------
# 공통
# -----------------------------
def clean_text(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first_value(obj, paths, default=""):
    """중첩 JSON에서 후보 경로 중 첫 번째 값을 반환."""
    for path in paths:
        cur = obj
        ok = True
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return default


def as_text(obj, paths, default=""):
    return clean_text(first_value(obj, paths, default))


def normalize_date(value):
    s = clean_text(value)
    if not s:
        return ""
    # 2026-10-02T... / 2026. 10. 02. / 2026-10-02 대응
    m = re.search(r"(20\d{2})[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})", s)
    if m:
        return f"{m.group(1)}. {int(m.group(2)):02d}. {int(m.group(3)):02d}."
    return s


def money_text(value):
    s = clean_text(value)
    if not s:
        return ""
    return s


def safe_get(url, params=None, timeout=20):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


# -----------------------------
# 새 Naver Research API
# -----------------------------
@st.cache_data(ttl=180)
def get_brokers():
    url = f"{API_BASE}/brokers"
    try:
        r = safe_get(url)
        data = r.json()
        items = data.get("items", data if isinstance(data, list) else [])
        result = []
        for x in items:
            code = first_value(x, ["brokerCode", "code", "id"])
            name = first_value(x, ["brokerName", "name", "label"])
            if code is not None and name:
                result.append({"code": str(code), "name": clean_text(name)})
        return result
    except Exception:
        return []


def extract_items(data):
    if isinstance(data, dict):
        for key in ("items", "researchSets", "contents", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        # 일부 응답이 researchSets 안에 items를 둘 수 있음
        for value in data.values():
            if isinstance(value, dict):
                items = extract_items(value)
                if items:
                    return items
    elif isinstance(data, list):
        return data
    return []


def normalize_research_item(x):
    # 실제 응답 구조가 일부 변경되어도 여러 후보를 순차적으로 탐색
    nid = first_value(x, [
        "nid", "researchId", "id", "researchContent.nid"
    ])

    title = as_text(x, [
        "title",
        "researchTitle",
        "researchContent.title",
        "content.title",
        "research.title",
    ])

    lead = as_text(x, [
        "leadtext",
        "leadText",
        "summary",
        "description",
        "researchContent.leadtext",
        "researchContent.leadText",
        "researchContent.summary",
        "researchContent.description",
        "content.leadtext",
    ])

    published = normalize_date(first_value(x, [
        "date",
        "publishDate",
        "publishedAt",
        "researchDate",
        "researchContent.date",
        "researchContent.publishDate",
    ]))

    broker = as_text(x, [
        "brokerName",
        "broker.name",
        "broker.label",
        "researchContent.brokerName",
        "issuerName",
        "press",
    ])

    stock = as_text(x, [
        "stockName",
        "itemName",
        "item.name",
        "stock.name",
        "researchContent.stockName",
        "researchContent.itemName",
    ])

    item_code = first_value(x, [
        "itemCode",
        "stockCode",
        "code",
        "item.code",
        "researchContent.itemCode",
    ])

    target = money_text(first_value(x, [
        "targetPrice",
        "targetPriceText",
        "goalPrice",
        "goalPriceText",
        "researchContent.targetPrice",
        "researchContent.goalPrice",
    ]))

    opinion = as_text(x, [
        "opinion",
        "investmentOpinion",
        "recommendation",
        "researchContent.opinion",
    ])

    industry = as_text(x, [
        "industry",
        "industryName",
        "researchContent.industry",
    ])

    return {
        "id": str(nid) if nid is not None else "",
        "date": published,
        "stock": stock,
        "code": str(item_code) if item_code is not None else "",
        "title": title,
        "summary": lead,
        "broker": broker,
        "target": target,
        "opinion": opinion,
        "industry": industry,
        "raw": x,
    }


@st.cache_data(ttl=180)
def get_research_api(
    index=0,
    size=20,
    query="",
    start_date="",
    end_date="",
    broker_codes=None,
    item_codes=None,
    industry_types=None,
):
    url = f"{API_BASE}/company"
    params = [("index", index), ("size", size)]

    if query:
        params.append(("query", query))
    if start_date:
        params.append(("startDate", start_date))
    if end_date:
        params.append(("endDate", end_date))

    for code in broker_codes or []:
        params.append(("brokerCodes", code))

    for code in item_codes or []:
        params.append(("itemCodes", code))

    for code in industry_types or []:
        params.append(("industryTypes", code))

    r = safe_get(url, params=params)
    data = r.json()

    items = [normalize_research_item(x) for x in extract_items(data)]

    # 화면 표시용 메타
    if isinstance(data, dict):
        total = data.get("totalCount")
        has_next = data.get("hasNext")
    else:
        total = None
        has_next = None

    return items, total, has_next


# -----------------------------
# HTML fallback
# 첨부된 새 페이지 HTML의 구조를 그대로 사용
# -----------------------------
@st.cache_data(ttl=180)
def get_research_html():
    r = safe_get(RESEARCH_URL)
    soup = BeautifulSoup(r.text, "html.parser")

    rows = []
    selectors = soup.select("a.ResearchList_research-item-link__OF48E")

    for a in selectors:
        title_el = a.select_one("h2.ResearchList_title__QEejC")
        date_el = a.select_one("span.ResearchList_date__tVIZb")
        lead_el = a.select_one("div.ResearchList_leadtext__xxbV9")
        broker_el = a.select_one("div.ResearchList_info__S_k_o span.press")
        stock_el = a.select_one("span.ResearchList_stock-name__RjQiE")

        target = ""
        opinion = ""
        for li in a.select("ul.ResearchList_stock-info-detail___ScFa li"):
            label = clean_text(li.select_one("span.ResearchList_label__eZsRs"))
            value = clean_text(li.select_one("span.ResearchList_value__7jpOl"))
            if label == "목표주가":
                target = value
            elif label == "투자의견":
                opinion = value

        href = a.get("href", "")
        rid = href.rstrip("/").split("/")[-1] if href else ""

        rows.append({
            "id": rid,
            "date": clean_text(date_el),
            "stock": clean_text(stock_el),
            "code": "",
            "title": clean_text(title_el),
            "summary": clean_text(lead_el),
            "broker": clean_text(broker_el),
            "target": target,
            "opinion": opinion,
            "industry": "",
            "raw": {},
        })

    return rows


def get_research(index, size, query, start_date, end_date, broker_codes):
    try:
        items, total, has_next = get_research_api(
            index=index,
            size=size,
            query=query,
            start_date=start_date,
            end_date=end_date,
            broker_codes=broker_codes,
        )

        # API가 정상적으로 데이터를 주면 API 결과 사용
        if items:
            return items, total, has_next, "API"
    except Exception as e:
        api_error = str(e)
    else:
        api_error = ""

    # API가 실패하거나 빈 응답이면 현재 HTML 구조로 fallback
    try:
        items = get_research_html()

        if query:
            q = query.lower()
            items = [
                x for x in items
                if q in (x["title"] + " " + x["summary"] + " " + x["stock"]).lower()
            ]

        if broker_codes:
            # HTML fallback에는 broker code가 없으므로 이름 필터는 하지 않음
            pass

        return items, len(items), False, "HTML fallback"
    except Exception as e:
        raise RuntimeError(
            f"네이버 리서치 데이터를 가져오지 못했습니다.\n"
            f"API 오류: {api_error}\n"
            f"HTML 오류: {e}"
        )


# -----------------------------
# 상세 API
# -----------------------------
@st.cache_data(ttl=300)
def get_research_detail(research_id):
    url = f"{API_BASE}/company/{research_id}"
    r = safe_get(url)
    return r.json()


def extract_detail(data):
    # 응답 전체를 너무 복잡하게 가정하지 않고 주요 HTML/텍스트 필드를 탐색
    content = data
    if isinstance(data, dict):
        for key in ("researchContent", "content", "research", "data"):
            if isinstance(data.get(key), dict):
                content = data[key]
                break

    title = as_text(content, ["title", "researchTitle", "subject"])
    date_ = normalize_date(first_value(content, [
        "date", "publishDate", "publishedAt", "researchDate"
    ]))
    broker = as_text(content, ["brokerName", "broker.name", "press", "issuerName"])
    stock = as_text(content, ["stockName", "itemName", "item.name"])
    target = money_text(first_value(content, [
        "targetPrice", "targetPriceText", "goalPrice", "goalPriceText"
    ]))
    opinion = as_text(content, ["opinion", "investmentOpinion", "recommendation"])

    body = first_value(content, [
        "body", "content", "html", "contents", "researchBody", "reportContent"
    ])

    return {
        "title": title,
        "date": date_,
        "broker": broker,
        "stock": stock,
        "target": target,
        "opinion": opinion,
        "body": body,
        "raw": data,
    }


# -----------------------------
# UI
# -----------------------------
st.set_page_config(
    page_title="네이버 증권 리서치",
    page_icon="📑",
    layout="wide",
)

st.title("📑 네이버 증권 리서치")
st.caption("새로운 stock.naver.com 리서치 페이지 대응 · API 우선 / HTML fallback")

with st.sidebar:
    st.header("검색 조건")

    query = st.text_input(
        "종목명·리서치 제목·내용",
        placeholder="예: 삼성전자, HBM, 반도체",
    )

    broker_map = {x["name"]: x["code"] for x in get_brokers()}
    broker_names = ["전체"] + sorted(broker_map.keys())

    selected_broker = st.selectbox("발행사", broker_names)

    today = date.today()
    default_start = today - timedelta(days=14)

    start = st.date_input("시작일", default_start)
    end = st.date_input("종료일", today)

    page_size = st.selectbox("한 페이지 표시", [10, 15, 20, 30, 50], index=2)

    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


broker_codes = []
if selected_broker != "전체":
    broker_codes = [broker_map[selected_broker]]

# API 날짜는 YYYY-MM-DD 형태 사용
start_date = start.strftime("%Y-%m-%d")
end_date = end.strftime("%Y-%m-%d")

if "page" not in st.session_state:
    st.session_state.page = 0

col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    if st.button("◀ 이전", disabled=st.session_state.page <= 0):
        st.session_state.page -= 1
        st.rerun()

with col2:
    if st.button("다음 ▶"):
        st.session_state.page += 1
        st.rerun()

page = st.session_state.page

try:
    rows, total, has_next, source = get_research(
        index=page,
        size=page_size,
        query=query.strip(),
        start_date=start_date,
        end_date=end_date,
        broker_codes=broker_codes,
    )
except Exception as e:
    st.error(str(e))
    st.stop()

with col3:
    if total:
        st.write(f"페이지 {page + 1} · 전체 {total:,}건 · 데이터: {source}")
    else:
        st.write(f"페이지 {page + 1} · 데이터: {source}")

st.divider()

if not rows:
    st.info("조건에 맞는 리서치가 없습니다.")
else:
    for row in rows:
        title = row["title"] or "(제목 없음)"
        stock = row["stock"] or "-"
        broker = row["broker"] or "-"
        dt = row["date"] or "-"
        target = row["target"] or "-"
        opinion = row["opinion"] or "-"
        summary = row["summary"] or ""

        with st.container(border=True):
            c1, c2 = st.columns([7, 2])

            with c1:
                if row["id"]:
                    st.markdown(
                        f"### [{stock}] {title}  "
                        f"[↗](https://stock.naver.com/research/company/{row['id']})"
                    )
                else:
                    st.markdown(f"### [{stock}] {title}")

                st.caption(f"{dt} · {broker}")

                if summary:
                    st.write(summary)

            with c2:
                st.metric("목표주가", target)
                st.metric("투자의견", opinion)

            if row["id"]:
                with st.expander("📄 리포트 상세"):
                    try:
                        detail_raw = get_research_detail(row["id"])
                        detail = extract_detail(detail_raw)

                        meta = []
                        if detail["stock"]:
                            meta.append(f"**종목:** {detail['stock']}")
                        if detail["broker"]:
                            meta.append(f"**증권사:** {detail['broker']}")
                        if detail["date"]:
                            meta.append(f"**작성일:** {detail['date']}")
                        if detail["target"]:
                            meta.append(f"**목표주가:** {detail['target']}")
                        if detail["opinion"]:
                            meta.append(f"**투자의견:** {detail['opinion']}")

                        if meta:
                            st.markdown(" · ".join(meta))

                        body = detail["body"]

                        if isinstance(body, str) and body.strip():
                            # HTML이면 렌더링, 일반 텍스트면 그대로 출력
                            if "<" in body and ">" in body:
                                st.markdown(body, unsafe_allow_html=True)
                            else:
                                st.write(body)
                        else:
                            # 응답 구조가 변경된 경우 raw JSON을 확인할 수 있게 함
                            st.json(detail_raw)

                    except Exception as e:
                        st.warning(f"상세 리포트를 불러오지 못했습니다: {e}")

st.divider()
st.caption(
    "주의: 네이버 증권의 공개 웹 페이지와 비공식 내부 API 구조를 이용합니다. "
    "네이버의 구조 변경에 따라 동작이 달라질 수 있습니다."
)
