import html
import re
from datetime import date, timedelta

import requests
import streamlit as st
from bs4 import BeautifulSoup


# ============================================================
# 네이버 증권 리서치
# stock.naver.com 새 페이지 대응
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
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
    "Referer": RESEARCH_URL,
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# 공통 함수
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        return ""

    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def first_value(obj, paths, default=""):
    """
    중첩 JSON에서 후보 경로 중
    실제 값이 존재하는 첫 번째 값을 반환
    """

    for path in paths:

        current = obj
        valid = True

        for key in path.split("."):

            if isinstance(current, dict) and key in current:
                current = current[key]

            else:
                valid = False
                break

        if valid and current not in (None, ""):
            return current

    return default


def as_text(obj, paths, default=""):
    return clean_text(
        first_value(obj, paths, default)
    )


def normalize_date(value):

    text = clean_text(value)

    if not text:
        return ""

    match = re.search(
        r"(20\d{2})[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})",
        text
    )

    if match:

        return (
            f"{match.group(1)}."
            f"{int(match.group(2)):02d}."
            f"{int(match.group(3)):02d}"
        )

    return text


def money_text(value):

    text = clean_text(value)

    if not text:
        return ""

    return text


def safe_get(url, params=None, timeout=20):

    response = session.get(
        url,
        params=params,
        timeout=timeout
    )

    response.raise_for_status()

    return response


# ============================================================
# 날짜 변환
# ============================================================

def date_key(value):

    text = clean_text(value)

    if not text:
        return None

    match = re.search(
        r"(20\d{2})[-./]\s*(\d{1,2})[-./]\s*(\d{1,2})",
        text
    )

    if not match:
        return None

    return date(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3))
    )


# ============================================================
# 증권사 목록
# ============================================================

@st.cache_data(ttl=180)
def get_brokers():

    url = f"{API_BASE}/brokers"

    try:

        response = safe_get(url)

        data = response.json()

        if isinstance(data, dict):

            items = data.get("items", [])

        elif isinstance(data, list):

            items = data

        else:

            items = []

        result = []

        for item in items:

            code = first_value(
                item,
                [
                    "brokerCode",
                    "code",
                    "id"
                ]
            )

            name = first_value(
                item,
                [
                    "brokerName",
                    "name",
                    "label"
                ]
            )

            if code is not None and name:

                result.append(
                    {
                        "code": str(code),
                        "name": clean_text(name)
                    }
                )

        return result

    except Exception:

        return []


# ============================================================
# API 응답에서 items 추출
# ============================================================

def extract_items(data):

    if isinstance(data, dict):

        # 실제 확인된 구조
        if isinstance(data.get("items"), list):

            return data["items"]

        # 혹시 구조가 변경되는 경우
        for key in (
            "researchSets",
            "contents",
            "data",
            "results"
        ):

            value = data.get(key)

            if isinstance(value, list):

                return value

        # 중첩 구조 대응
        for value in data.values():

            if isinstance(value, dict):

                items = extract_items(value)

                if items:

                    return items

    elif isinstance(data, list):

        return data

    return []


# ============================================================
# 리포트 1개 정규화
# ============================================================

def normalize_research_item(item):

    # 리포트 번호
    nid = first_value(
        item,
        [
            "nid",
            "researchId",
            "id"
        ]
    )

    # 제목
    title = as_text(
        item,
        [
            "title",
            "researchTitle",
            "subject"
        ]
    )

    # 내용
    content = as_text(
        item,
        [
            "content",
            "leadtext",
            "leadText",
            "summary",
            "description"
        ]
    )

    # 작성일
    write_date = normalize_date(
        first_value(
            item,
            [
                "writeDate",
                "date",
                "publishDate",
                "publishedAt",
                "researchDate"
            ]
        )
    )

    # 증권사
    broker = as_text(
        item,
        [
            "brokerName",
            "broker.name",
            "broker.label",
            "issuerName",
            "press"
        ]
    )

    # 종목명
    stock = as_text(
        item,
        [
            "itemName",
            "stockName",
            "item.name",
            "stock.name"
        ]
    )

    # 종목코드
    item_code = first_value(
        item,
        [
            "itemCode",
            "stockCode",
            "code"
        ]
    )

    # 목표주가
    target = money_text(
        first_value(
            item,
            [
                "goalPrice",
                "goalPriceText",
                "targetPrice",
                "targetPriceText"
            ]
        )
    )

    # 투자의견
    opinion = as_text(
        item,
        [
            "opinionText",
            "opinion",
            "investmentOpinion",
            "recommendation"
        ]
    )

    return {
        "id": str(nid) if nid is not None else "",
        "date": write_date,
        "stock": stock,
        "code": (
            str(item_code)
            if item_code is not None
            else ""
        ),
        "title": title,
        "summary": content,
        "broker": broker,
        "target": target,
        "opinion": opinion,
        "raw": item,
    }


# ============================================================
# 네이버 리서치 API
#
# 실제 확인된 요청
#
# /api/stockSecurity/researches/v2/company
# ?index=0
# &size=15
# &query=삼성전자
#
# ============================================================

@st.cache_data(ttl=180)
def get_research_api(
    index=0,
    size=15,
    query=""
):

    url = f"{API_BASE}/company"

    params = [
        ("index", int(index)),
        ("size", int(size)),
    ]

    if clean_text(query):

        params.append(
            (
                "query",
                clean_text(query)
            )
        )

    response = safe_get(
        url,
        params=params
    )

    data = response.json()

    raw_items = extract_items(data)

    items = [
        normalize_research_item(item)
        for item in raw_items
    ]

    if isinstance(data, dict):

        total = data.get(
            "totalCount"
        )

        has_next = data.get(
            "hasNext"
        )

    else:

        total = None
        has_next = None

    return (
        items,
        total,
        has_next
    )


# ============================================================
# 날짜 / 증권사 필터
# ============================================================

def apply_local_filters(
    items,
    start_date="",
    end_date="",
    broker_codes=None
):

    start_obj = (
        date_key(start_date)
        if start_date
        else None
    )

    end_obj = (
        date_key(end_date)
        if end_date
        else None
    )

    broker_codes = {
        str(x)
        for x in (broker_codes or [])
    }

    result = []

    for item in items:

        item_date = date_key(
            item.get("date", "")
        )

        # 시작일
        if (
            start_obj
            and item_date
            and item_date < start_obj
        ):
            continue

        # 종료일
        if (
            end_obj
            and item_date
            and item_date > end_obj
        ):
            continue

        # 증권사
        if broker_codes:

            raw = item.get("raw") or {}

            broker_code = first_value(
                raw,
                [
                    "brokerCode",
                    "broker.code"
                ]
            )

            if (
                broker_code is None
                or str(broker_code)
                not in broker_codes
            ):
                continue

        result.append(item)

    return result


# ============================================================
# 검색
#
# 중요:
# 실제 API Response를 확인한 결과
# query=삼성전자를 보내도 items에 여러 종목이
# 함께 들어올 수 있음.
#
# 따라서 API query + 로컬 검색을 같이 사용한다.
# ============================================================

def filter_research_items(
    items,
    query
):

    q = clean_text(query).lower()

    if not q:

        return items

    result = []

    for item in items:

        search_text = " ".join(
            [
                item.get("stock", ""),
                item.get("code", ""),
                item.get("title", ""),
                item.get("summary", ""),
                item.get("broker", ""),
            ]
        ).lower()

        if q in search_text:

            result.append(item)

    return result


# ============================================================
# HTML fallback
# ============================================================

@st.cache_data(ttl=180)
def get_research_html():

    response = safe_get(
        RESEARCH_URL
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    rows = []

    selectors = soup.select(
        "a.ResearchList_research-item-link__OF48E"
    )

    for item in selectors:

        title_el = item.select_one(
            "h2.ResearchList_title__QEejC"
        )

        date_el = item.select_one(
            "span.ResearchList_date__tVIZb"
        )

        lead_el = item.select_one(
            "div.ResearchList_leadtext__xxbV9"
        )

        broker_el = item.select_one(
            "div.ResearchList_info__S_k_o span.press"
        )

        stock_el = item.select_one(
            "span.ResearchList_stock-name__RjQiE"
        )

        target = ""

        opinion = ""

        for li in item.select(
            "ul.ResearchList_stock-info-detail___ScFa li"
        ):

            label = clean_text(
                li.select_one(
                    "span.ResearchList_label__eZsRs"
                )
            )

            value = clean_text(
                li.select_one(
                    "span.ResearchList_value__7jpOl"
                )
            )

            if label == "목표주가":

                target = value

            elif label == "투자의견":

                opinion = value

        href = item.get(
            "href",
            ""
        )

        report_id = (
            href.rstrip("/")
            .split("/")[-1]
            if href
            else ""
        )

        rows.append(
            {
                "id": report_id,
                "date": clean_text(date_el),
                "stock": clean_text(stock_el),
                "code": "",
                "title": clean_text(title_el),
                "summary": clean_text(lead_el),
                "broker": clean_text(broker_el),
                "target": target,
                "opinion": opinion,
                "raw": {},
            }
        )

    return rows


# ============================================================
# 핵심 데이터 조회
# ============================================================

def get_research(
    page,
    page_size,
    query,
    start_date,
    end_date,
    broker_codes
):

    api_error = ""

    try:

        # ----------------------------------------------------
        # Streamlit 페이지 번호
        # ----------------------------------------------------

        target_start = (
            page * page_size
        )

        target_end = (
            target_start + page_size
        )

        matched = []

        api_total = None

        api_index = 0

        has_next = True

        start_obj = (
            date_key(start_date)
            if start_date
            else None
        )

        # ----------------------------------------------------
        # API 페이지를 필요한 만큼 읽는다.
        #
        # 네이버 API는 size=15 기준으로 가져온다.
        # ----------------------------------------------------

        while (
            has_next
            and api_index < 300
        ):

            items, total, next_flag = (
                get_research_api(
                    index=api_index,
                    size=15,
                    query=query.strip()
                )
            )

            if api_total is None:

                api_total = total

            if not items:

                break

            # ------------------------------------------------
            # 날짜 / 증권사
            # ------------------------------------------------

            filtered = apply_local_filters(
                items,
                start_date=start_date,
                end_date=end_date,
                broker_codes=broker_codes
            )

            # ------------------------------------------------
            # 검색어
            #
            # 이 부분이 핵심
            # ------------------------------------------------

            filtered = filter_research_items(
                filtered,
                query
            )

            matched.extend(
                filtered
            )

            # ------------------------------------------------
            # 최신순이므로 시작일보다 오래된 자료가
            # 나오면 더 이상 내려갈 필요가 없다.
            # ------------------------------------------------

            if start_obj:

                dates = [
                    date_key(
                        x.get(
                            "date",
                            ""
                        )
                    )
                    for x in items
                ]

                dates = [
                    x
                    for x in dates
                    if x is not None
                ]

                if (
                    dates
                    and min(dates) < start_obj
                ):

                    has_next = False

                    break

            # ------------------------------------------------
            # 다음 API 페이지
            # ------------------------------------------------

            has_next = bool(
                next_flag
            )

            api_index += 1

            # ------------------------------------------------
            # 현재 화면에 필요한 만큼 확보
            # ------------------------------------------------

            if (
                len(matched)
                >= target_end
            ):

                break

        # ----------------------------------------------------
        # 현재 Streamlit 페이지에 해당하는 결과
        # ----------------------------------------------------

        page_items = matched[
            target_start:target_end
        ]

        # ----------------------------------------------------
        # 전체 건수
        # ----------------------------------------------------

        if (
            not query.strip()
            and not start_date
            and not end_date
            and not broker_codes
        ):

            display_total = api_total

        else:

            display_total = len(
                matched
            )

            if (
                has_next
                and len(matched)
                >= target_end
            ):

                display_total = (
                    f"{len(matched)}+"
                )

        # ----------------------------------------------------
        # 다음 페이지 존재 여부
        # ----------------------------------------------------

        more = bool(
            has_next
            and (
                len(matched)
                > target_end
                or len(matched)
                >= target_end
            )
        )

        return (
            page_items,
            display_total,
            more,
            "API"
        )

    except Exception as error:

        api_error = str(error)

    # ========================================================
    # API 실패 → HTML fallback
    # ========================================================

    try:

        items = get_research_html()

        items = apply_local_filters(
            items,
            start_date,
            end_date,
            broker_codes
        )

        items = filter_research_items(
            items,
            query
        )

        start_index = (
            page * page_size
        )

        page_items = items[
            start_index:
            start_index + page_size
        ]

        return (
            page_items,
            len(items),
            (
                start_index
                + page_size
                < len(items)
            ),
            "HTML fallback"
        )

    except Exception as html_error:

        raise RuntimeError(
            "네이버 리서치 데이터를 "
            "가져오지 못했습니다.\n\n"
            f"API 오류: {api_error}\n\n"
            f"HTML 오류: {html_error}"
        )


# ============================================================
# 상세 리포트
# ============================================================

@st.cache_data(ttl=300)
def get_research_detail(
    research_id
):

    url = (
        f"{API_BASE}/company/"
        f"{research_id}"
    )

    response = safe_get(url)

    return response.json()


def extract_detail(data):

    content = data

    if isinstance(data, dict):

        for key in (
            "researchContent",
            "content",
            "research",
            "data"
        ):

            if isinstance(
                data.get(key),
                dict
            ):

                content = data[key]

                break

    title = as_text(
        content,
        [
            "title",
            "researchTitle",
            "subject"
        ]
    )

    report_date = normalize_date(
        first_value(
            content,
            [
                "date",
                "writeDate",
                "publishDate",
                "publishedAt",
                "researchDate"
            ]
        )
    )

    broker = as_text(
        content,
        [
            "brokerName",
            "broker.name",
            "press",
            "issuerName"
        ]
    )

    stock = as_text(
        content,
        [
            "stockName",
            "itemName",
            "item.name"
        ]
    )

    target = money_text(
        first_value(
            content,
            [
                "targetPrice",
                "targetPriceText",
                "goalPrice",
                "goalPriceText"
            ]
        )
    )

    opinion = as_text(
        content,
        [
            "opinionText",
            "opinion",
            "investmentOpinion",
            "recommendation"
        ]
    )

    body = first_value(
        content,
        [
            "body",
            "content",
            "html",
            "contents",
            "researchBody",
            "reportContent"
        ]
    )

    return {
        "title": title,
        "date": report_date,
        "broker": broker,
        "stock": stock,
        "target": target,
        "opinion": opinion,
        "body": body,
        "raw": data,
    }


# ============================================================
# Streamlit UI
# ============================================================

st.set_page_config(
    page_title="네이버 증권 리서치",
    page_icon="📑",
    layout="wide"
)


st.title(
    "📑 네이버 증권 리서치"
)

st.caption(
    "stock.naver.com 리서치 페이지 대응 "
    "· 실제 API + 검색 보정"
)


# ============================================================
# 사이드바
# ============================================================

with st.sidebar:

    st.header(
        "검색 조건"
    )

    query = st.text_input(
        "종목명·리서치 제목·내용",
        placeholder=(
            "예: 삼성전자, HBM, 반도체"
        )
    )

    # --------------------------------------------------------
    # 증권사
    # --------------------------------------------------------

    broker_list = get_brokers()

    broker_map = {
        item["name"]: item["code"]
        for item in broker_list
    }

    broker_names = [
        "전체"
    ] + sorted(
        broker_map.keys()
    )

    selected_broker = st.selectbox(
        "발행사",
        broker_names
    )

    # --------------------------------------------------------
    # 날짜
    # --------------------------------------------------------

    today = date.today()

    default_start = (
        today - timedelta(days=14)
    )

    start = st.date_input(
        "시작일",
        default_start
    )

    end = st.date_input(
        "종료일",
        today
    )

    # --------------------------------------------------------
    # 페이지 크기
    # --------------------------------------------------------

    page_size = st.selectbox(
        "한 페이지 표시",
        [
            10,
            15,
            20,
            30,
            50
        ],
        index=2
    )

    # --------------------------------------------------------
    # 새로고침
    # --------------------------------------------------------

    if st.button(
        "🔄 새로고침",
        use_container_width=True
    ):

        st.cache_data.clear()

        st.rerun()


# ============================================================
# 선택한 증권사 코드
# ============================================================

broker_codes = []

if selected_broker != "전체":

    broker_codes = [
        broker_map[
            selected_broker
        ]
    ]


# ============================================================
# 날짜 문자열
# ============================================================

start_date = start.strftime(
    "%Y-%m-%d"
)

end_date = end.strftime(
    "%Y-%m-%d"
)


# ============================================================
# 검색 조건 변경 시 1페이지로 이동
# ============================================================

filter_signature = (
    query.strip(),
    selected_broker,
    start.isoformat(),
    end.isoformat(),
    page_size,
)


if "page" not in st.session_state:

    st.session_state.page = 0


if (
    st.session_state.get(
        "filter_signature"
    )
    != filter_signature
):

    st.session_state.page = 0

    st.session_state.filter_signature = (
        filter_signature
    )


# ============================================================
# 페이지 버튼
# ============================================================

col1, col2, col3 = st.columns(
    [1, 1, 4]
)


with col1:

    if st.button(
        "◀ 이전",
        disabled=(
            st.session_state.page <= 0
        )
    ):

        st.session_state.page -= 1

        st.rerun()


with col2:

    if st.button(
        "다음 ▶"
    ):

        st.session_state.page += 1

        st.rerun()


page = st.session_state.page


# ============================================================
# 데이터 조회
# ============================================================

try:

    rows, total, has_next, source = (
        get_research(
            page=page,
            page_size=page_size,
            query=query.strip(),
            start_date=start_date,
            end_date=end_date,
            broker_codes=broker_codes
        )
    )

except Exception as error:

    st.error(
        str(error)
    )

    st.stop()


# ============================================================
# 상단 정보
# ============================================================

with col3:

    total_display = None

    if total not in (
        None,
        ""
    ):

        try:

            total_display = (
                f"{int(total):,}"
            )

        except (
            TypeError,
            ValueError
        ):

            total_display = str(
                total
            )

    if total_display:

        st.write(
            f"페이지 {page + 1} "
            f"· 전체 {total_display}건 "
            f"· 데이터: {source}"
        )

    else:

        st.write(
            f"페이지 {page + 1} "
            f"· 데이터: {source}"
        )


st.divider()


# ============================================================
# 검색 결과 없음
# ============================================================

if not rows:

    st.info(
        "조건에 맞는 리서치가 없습니다."
    )


# ============================================================
# 리서치 출력
# ============================================================

else:

    for row in rows:

        title = (
            row["title"]
            or "(제목 없음)"
        )

        stock = (
            row["stock"]
            or "-"
        )

        broker = (
            row["broker"]
            or "-"
        )

        report_date = (
            row["date"]
            or "-"
        )

        target = (
            row["target"]
            or "-"
        )

        opinion = (
            row["opinion"]
            or "-"
        )

        summary = (
            row["summary"]
            or ""
        )


        with st.container(
            border=True
        ):

            c1, c2 = st.columns(
                [7, 2]
            )


            # =================================================
            # 왼쪽
            # =================================================

            with c1:

                if row["id"]:

                    st.markdown(
                        f"### [{stock}] "
                        f"{title}  "
                        f"[↗]("
                        f"https://stock.naver.com/"
                        f"research/company/"
                        f"{row['id']}"
                        f")"
                    )

                else:

                    st.markdown(
                        f"### [{stock}] "
                        f"{title}"
                    )


                st.caption(
                    f"{report_date}"
                    f" · "
                    f"{broker}"
                )


                if summary:

                    st.write(
                        summary
                    )


            # =================================================
            # 오른쪽
            # =================================================

            with c2:

                st.metric(
                    "목표주가",
                    target
                )

                st.metric(
                    "투자의견",
                    opinion
                )


            # =================================================
            # 상세 리포트
            # =================================================

            if row["id"]:

                with st.expander(
                    "📄 리포트 상세"
                ):

                    try:

                        detail_raw = (
                            get_research_detail(
                                row["id"]
                            )
                        )

                        detail = (
                            extract_detail(
                                detail_raw
                            )
                        )


                        meta = []


                        if detail["stock"]:

                            meta.append(
                                f"**종목:** "
                                f"{detail['stock']}"
                            )


                        if detail["broker"]:

                            meta.append(
                                f"**증권사:** "
                                f"{detail['broker']}"
                            )


                        if detail["date"]:

                            meta.append(
                                f"**작성일:** "
                                f"{detail['date']}"
                            )


                        if detail["target"]:

                            meta.append(
                                f"**목표주가:** "
                                f"{detail['target']}"
                            )


                        if detail["opinion"]:

                            meta.append(
                                f"**투자의견:** "
                                f"{detail['opinion']}"
                            )


                        if meta:

                            st.markdown(
                                " · ".join(meta)
                            )


                        body = detail[
                            "body"
                        ]


                        if (
                            isinstance(
                                body,
                                str
                            )
                            and body.strip()
                        ):

                            if (
                                "<"
                                in body
                                and ">"
                                in body
                            ):

                                st.markdown(
                                    body,
                                    unsafe_allow_html=True
                                )

                            else:

                                st.write(
                                    body
                                )

                        else:

                            st.json(
                                detail_raw
                            )


                    except Exception as error:

                        st.warning(
                            "상세 리포트를 "
                            "불러오지 못했습니다: "
                            f"{error}"
                        )


st.divider()


st.caption(
    "주의: 네이버 증권의 공개 웹 페이지와 "
    "비공식 내부 API 구조를 이용합니다. "
    "네이버의 구조 변경에 따라 동작이 달라질 수 있습니다."
)
