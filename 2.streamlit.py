import html
import re
import html
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
        "content",
        "researchContent.leadtext",
        "researchContent.leadText",
        "researchContent.summary",
        "researchContent.description",
        "content.leadtext",
    ])

    published = normalize_date(first_value(x, [
        "writeDate",
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
        "opinionText",
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
def get_research_api(index=0, size=15, query=""):
    """네이버 실제 페이지가 사용하는 API 호출을 그대로 재현한다.

    실제 Network 확인 결과:
      GET /api/stockSecurity/researches/v2/company
      ?index=0&size=15&query=삼성전자

    따라서 날짜/증권사 등의 임의 파라미터는 이 함수에 넣지 않는다.
    네이버 API가 반환한 결과에 대해 화면에서 추가 필터를 적용한다.
    """
    url = f"{API_BASE}/company"
    params = [("index", int(index)), ("size", int(size))]
    if clean_text(query):
        params.append(("query", clean_text(query)))

    r = safe_get(url, params=params)
    data = r.json()

    items = [normalize_research_item(x) for x in extract_items(data)]
    if isinstance(data, dict):
        total = data.get("totalCount")
        has_next = data.get("hasNext")
    else:
        total = None
        has_next = None

    return items, total, has_next


def _date_key(value):
    s = clean_text(value)
    m = re.search(r"(20\d{2})[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})", s)
    if not m:
        return None
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def apply_local_filters(items, start_date="", end_date="", broker_codes=None):
    """네이버 API 응답에 대해 날짜/증권사 필터를 적용한다."""
    start_obj = _date_key(start_date) if start_date else None
    end_obj = _date_key(end_date) if end_date else None
    broker_codes = {str(x) for x in (broker_codes or [])}

    result = []
    for row in items:
        d = _date_key(row.get("date", ""))

        if start_obj and d and d < start_obj:
            continue
        if end_obj and d and d > end_obj:
            continue

        if broker_codes:
            raw = row.get("raw") or {}
            broker_code = first_value(raw, ["brokerCode", "broker.code"])
            if broker_code is None or str(broker_code) not in broker_codes:
                continue

        result.append(row)

    return result


def filter_research_items(items, query):
    """HTML fallback에서 사용하는 로컬 검색."""
    q = clean_text(query).lower()
    if not q:
        return items
    result = []
    for x in items:
        haystack = " ".join([
            x.get("stock", ""),
            x.get("title", ""),
            x.get("summary", ""),
            x.get("broker", ""),
            x.get("industry", ""),
        ]).lower()
        if q in haystack:
            result.append(x)
    return result


def get_research(index, size, query, start_date, end_date, broker_codes):
    """네이버의 실제 검색 API를 사용해 페이지를 구성한다.

    검색어가 있으면 API의 query 파라미터를 직접 사용한다.
    날짜/증권사 필터로 일부 결과가 제외될 수 있으므로 필요한 경우
    다음 API 페이지도 순차적으로 읽어 현재 화면을 채운다.
    """
    api_error = ""

    try:
        target_start = index * size
        filtered = []
        api_total = None
        api_page = 0
        has_next = True
        scanned = 0

        # 네이버 결과는 최신순이므로 날짜 범위가 명확하면 시작일보다
        # 오래된 결과가 나온 시점에서 더 이상 읽지 않는다.
        while has_next and api_page < 100:
            items, total, next_flag = get_research_api(
                index=api_page,
                size=15,
                query=query.strip(),
            )
            scanned += len(items)
            if api_total is None:
                api_total = total

            if not items:
                break

            page_filtered = apply_local_filters(
                items,
                start_date=start_date,
                end_date=end_date,
                broker_codes=broker_codes,
            )
            filtered.extend(page_filtered)

            # 현재 API 페이지에서 시작일보다 오래된 자료가 등장하면
            # 이후 페이지도 더 오래된 자료일 가능성이 높으므로 중단한다.
            start_obj = _date_key(start_date) if start_date else None
            if start_obj:
                parsed_dates = [_date_key(x.get("date", "")) for x in items]
                parsed_dates = [x for x in parsed_dates if x is not None]
                if parsed_dates and min(parsed_dates) < start_obj:
                    has_next = False
                    break

            has_next = bool(next_flag)
            api_page += 1

            # 화면에 필요한 페이지까지 충분히 확보했고, 추가 필터가 없다면
            # 해당 API 페이지 하나만으로 바로 반환한다.
            if not start_date and not end_date and not broker_codes and len(filtered) >= target_start + size:
                break

        page_items = filtered[target_start:target_start + size]

        # 로컬 필터가 없는 경우 totalCount는 네이버가 직접 계산한 정확한 값이다.
        # 로컬 필터가 있는 경우에는 전체 결과 수를 정확히 계산하기 위해
        # 모든 페이지를 읽지는 않고, 현재 확보한 결과를 기준으로 표시한다.
        if start_date or end_date or broker_codes:
            display_total = len(filtered)
            if has_next and len(filtered) <= target_start + size:
                display_total = f"{len(filtered)}+"
        else:
            display_total = api_total

        return page_items, display_total, bool(has_next and (target_start + size < len(filtered) or api_page < 100)), "API"

    except Exception as e:
        api_error = str(e)

    # API가 실패하면 현재 HTML 구조로 fallback
    try:
        items = get_research_html()
        items = apply_local_filters(items, start_date, end_date, broker_codes)
        if query:
            items = filter_research_items(items, query)
        start_idx = index * size
        return items[start_idx:start_idx + size], len(items), start_idx + size < len(items), "HTML fallback"
    except Exception as e:
        raise RuntimeError(
            f"네이버 리서치 데이터를 가져오지 못했습니다.\n"
            f"API 오류: {api_error}\n"
            f"HTML 오류: {e}"
        )


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


@st.cache_data(ttl=180)
def get_all_research_api(start_date="", end_date="", broker_codes=None, max_pages=30):
    """검색을 위해 API 목록을 여러 페이지 가져온다.

    새 네이버 리서치 API에서 query 파라미터가 검색어를 제대로 적용하지 않는
    경우가 있어, 검색어는 가져온 리서치 목록에 대해 로컬에서 적용한다.
    현재 전체 건수가 많지 않으므로 최대 30페이지까지 안전하게 순회한다.
    """
    all_items = []
    total = None

    for idx in range(max_pages):
        items, page_total, has_next = get_research_api(
            index=idx,
            size=50,
            query="",
            start_date=start_date,
            end_date=end_date,
            broker_codes=broker_codes,
        )

        if page_total not in (None, ""):
            try:
                total = int(page_total)
            except (TypeError, ValueError):
                total = page_total

        if not items:
            break

        all_items.extend(items)

        # API가 hasNext를 주는 경우 우선 사용한다.
        if has_next is False:
            break

        # totalCount를 알 수 있으면 필요한 만큼만 가져온다.
        if isinstance(total, int) and len(all_items) >= total:
            break

    return all_items, total


def filter_research_items(items, query):
    """종목명/제목/내용/증권사를 대상으로 검색한다."""
    q = clean_text(query).lower()
    if not q:
        return items

    result = []
    for x in items:
        haystack = " ".join([
            x.get("stock", ""),
            x.get("title", ""),
            x.get("summary", ""),
            x.get("broker", ""),
            x.get("industry", ""),
        ]).lower()
        if q in haystack:
            result.append(x)
    return result


def filter_research_items(items, query):
    """HTML fallback에서 사용하는 로컬 검색."""
    q = clean_text(query).lower()
    if not q:
        return items
    result = []
    for x in items:
        haystack = " ".join([
            x.get("stock", ""),
            x.get("title", ""),
            x.get("summary", ""),
            x.get("broker", ""),
            x.get("industry", ""),
        ]).lower()
        if q in haystack:
            result.append(x)
    return result


def get_research(index, size, query, start_date, end_date, broker_codes):
    api_error = ""

    try:
        if query:
            # 검색어가 있으면 전체 목록을 가져온 뒤 로컬 검색한다.
            all_items, api_total = get_all_research_api(
                start_date=start_date,
                end_date=end_date,
                broker_codes=broker_codes,
            )
            filtered = filter_research_items(all_items, query)

            start_idx = index * size
            page_items = filtered[start_idx:start_idx + size]
            has_next = start_idx + size < len(filtered)
            return page_items, len(filtered), has_next, "API · 검색"

        # 검색어가 없으면 기존처럼 API 페이지 단위로 가져온다.
        items, total, has_next = get_research_api(
            index=index,
            size=size,
            query="",
            start_date=start_date,
            end_date=end_date,
            broker_codes=broker_codes,
        )

        if items:
            return items, total, has_next, "API"

    except Exception as e:
        api_error = str(e)

    # API가 실패하거나 빈 응답이면 현재 HTML 구조로 fallback
    try:
        items = get_research_html()

        if query:
            items = filter_research_items(items, query)

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

# 검색 조건이 바뀌면 이전 페이지 번호를 유지하지 않고 1페이지로 이동한다.
# 예: 전체 목록에서 2페이지를 보고 있다가 '삼성전자'를 검색하면
# 2페이지의 결과만 검색하는 문제가 생기므로 반드시 페이지를 초기화한다.
filter_signature = (
    query.strip(),
    selected_broker,
    start.isoformat(),
    end.isoformat(),
    page_size,
)

if "page" not in st.session_state:
    st.session_state.page = 0

if st.session_state.get("filter_signature") != filter_signature:
    st.session_state.page = 0
    st.session_state.filter_signature = filter_signature

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
    # 네이버 API의 totalCount가 숫자/문자열/None 중 어떤 형태로 와도 안전하게 처리
    total_display = None
    if total not in (None, ""):
        try:
            total_display = f"{int(total):,}"
        except (TypeError, ValueError):
            total_display = str(total)

    if total_display:
        st.write(f"페이지 {page + 1} · 전체 {total_display}건 · 데이터: {source}")
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
