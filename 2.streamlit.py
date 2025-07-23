import streamlit as st
import requests
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
import time

def get_report_list(page=1):
    url = f"https://finance.naver.com/research/company_list.naver?&page={page}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    reports = []

    table = soup.select_one('table.type_1')
    rows = table.select('tr')

    for row in rows:
        cols = row.find_all('td')
        if len(cols) >= 6:
            try:
                item_name = cols[0].select_one('a.stock_item').get_text(strip=True)
                title = cols[1].select_one('a').get_text(strip=True)
                company = cols[2].get_text(strip=True)
                date = cols[4].get_text(strip=True)

                href = cols[1].select_one('a')['href']
                parsed_url = urlparse(href)
                query_params = parse_qs(parsed_url.query)
                nid = query_params.get('nid', [''])[0]

                report = {
                    "item_name": item_name,
                    "title": title,
                    "company": company,
                    "date": date,
                    "nid": nid
                }

                reports.append(report)
            except Exception:
                continue
    return reports


def get_report_detail(nid):
    url = f'https://finance.naver.com/research/company_read.naver?nid={nid}'
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    sub_table = soup.select_one('table.type_1')

    money = sub_table.select_one(".money").text.strip() if sub_table.select_one(".money") else "-"
    coment = sub_table.select_one(".coment").text.strip() if sub_table.select_one(".coment") else "-"

    th_tag = sub_table.select_one('.view_sbj')
    text_parts = [t for t in th_tag.contents if t.name is None and t.strip()] if th_tag else []
    sub_title = text_parts[0].strip() if text_parts else ''

    p_tags = sub_table.select('.view_cnt > div > p')

    sub_content1 = p_tags[0].text.strip() if len(p_tags) > 0 else ''
    sub_content2 = '\n'.join(p.text.strip() for p in p_tags[1:]) if len(p_tags) > 1 else ''

    return {
        "목표가": money,
        "투자의견": coment,
        "제목": sub_title,
        "소제목": sub_content1,
        "내용": sub_content2
    }


# --- Streamlit UI ---
st.title("📊 네이버 증권 리서치 크롤러")

page = st.number_input("페이지 번호 선택", min_value=1, max_value=100, value=1)

if st.button("리포트 목록 불러오기"):
    with st.spinner("데이터 크롤링 중..."):
        reports = get_report_list(page)

        for i, report in enumerate(reports):
            with st.expander(f"{report['item_name']} | {report['title']} ({report['company']}, {report['date']})"):
                detail = get_report_detail(report['nid'])
                st.write(f"**목표가**: {detail['목표가']}")
                st.write(f"**투자의견**: {detail['투자의견']}")
                st.write(f"**제목**: {detail['제목']}")
                st.write(f"**소제목**: {detail['소제목']}")
                st.text_area("📄 본문 내용", detail['내용'], height=200, key=f"body_{report['nid']}")

                time.sleep(0.3)
