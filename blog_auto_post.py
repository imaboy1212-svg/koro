import os
import re
import time
import json
import requests
from google import genai
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BLOG_ID = os.environ.get("BLOG_ID")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY 환경변수가 설정되지 않았습니다.")
if not BLOG_ID:
    raise ValueError("BLOG_ID 환경변수가 설정되지 않았습니다.")

token_json_content = os.environ.get("GOOGLE_TOKEN_JSON")
if not token_json_content:
    raise ValueError("GOOGLE_TOKEN_JSON 환경변수가 설정되지 않았습니다.")
with open('token.json', 'w') as f:
    f.write(token_json_content)

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
model_name = 'gemini-2.5-flash'
print(f"✅ Using model: {model_name}\n")

AD_DISPLAY = """<div style="margin:28px 0;">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6858780475640766"
     crossorigin="anonymous"></script>
<!-- 디스플레이광고 -->
<ins class="adsbygoogle"
     style="display:block"
     data-ad-client="ca-pub-6858780475640766"
     data-ad-slot="1825484842"
     data-ad-format="auto"
     data-full-width-responsive="true"></ins>
<script>
     (adsbygoogle = window.adsbygoogle || []).push({});
</script>
</div>"""

AD_AUTORELAXED = """<div style="margin:28px 0;">
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-6858780475640766"
     crossorigin="anonymous"></script>
<ins class="adsbygoogle"
     style="display:block"
     data-ad-format="autorelaxed"
     data-ad-client="ca-pub-6858780475640766"
     data-ad-slot="3873632172"></ins>
<script>
     (adsbygoogle = window.adsbygoogle || []).push({});
</script>
</div>"""

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ 텔레그램 설정 없음. 전송 건너뜁니다.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print("✅ 텔레그램 전송 완료")
        else:
            print(f"⚠️ 텔레그램 전송 실패: {resp.text}")
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 오류: {e}")

def strip_all_links(body):
    body = re.sub(r'\s*\(<a\b[^>]*>.*?</a>\)', '', body, flags=re.DOTALL)
    body = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', body, flags=re.DOTALL)
    return body

def build_top_cta(title: str) -> str:
    return (
        '<div style="background:#e8f4fd;border-left:4px solid #339af0;'
        'padding:14px 20px;border-radius:0 8px 8px 0;margin-bottom:1.6em;">'
        '<p style="margin:0 0 4px 0;font-size:12px;font-weight:700;'
        'color:#339af0;letter-spacing:0.06em;">📌 TODAY\'S ISSUE</p>'
        f'<p style="margin:0;font-size:15px;font-weight:700;color:#1c3d5a;">{title}</p>'
        '</div>'
    )

def insert_ad_after_first_chapter(body: str, ad: str) -> str:
    pattern = r'(<h3\b[^>]*>)'
    parts = re.split(pattern, body, maxsplit=2)
    if len(parts) == 5:
        return parts[0] + parts[1] + parts[2] + ad + parts[3] + parts[4]
    return body + ad

def build_representative_image(articles):
    for a in articles:
        if a.get('image'):
            return (
                f'<div style="text-align:center; margin-bottom:1.8em;">'
                f'<img src="{a["image"]}" alt="{a["title"]}" '
                f'style="max-width:100%; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.1);">'
                f'</div>\n'
            )
    return ''

def build_related_articles_section(articles):
    valid = [a for a in articles if a.get('url')]
    if not valid:
        return ''
    items = ''
    for a in valid[:6]:
        if a.get('image'):
            items += (
                f'<li style="margin-bottom:1em; display:flex; align-items:center; gap:12px;">'
                f'<img src="{a["image"]}" alt="" '
                f'style="width:80px; height:54px; object-fit:cover; border-radius:4px; flex-shrink:0;">'
                f'<a href="{a["url"]}" target="_blank" rel="noopener" '
                f'style="color:#339af0; text-decoration:none; font-size:14px;">{a["title"]}</a>'
                f'</li>'
            )
        else:
            items += (
                f'<li style="margin-bottom:0.6em;">'
                f'<a href="{a["url"]}" target="_blank" rel="noopener" '
                f'style="color:#339af0; text-decoration:none;">{a["title"]}</a>'
                f'</li>'
            )
    return (
        '<div style="margin-top:2em; padding:16px 20px; background:#f8f9fa;'
        ' border-radius:8px; border:1px solid #e9ecef;">'
        '<p style="margin:0 0 12px 0; font-size:14px; font-weight:700; color:#495057;">관련 기사</p>'
        f'<ul style="margin:0; padding-left:0; list-style:none;">{items}</ul>'
        '</div>'
    )

def fetch_article_image(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.naver.com'
        }
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')
        tag = soup.select_one('meta[property="og:image"]')
        if tag:
            src = tag.get('content', '')
            if src.startswith('http'):
                return src
        return None
    except Exception:
        return None

def resolve_naver_url(url):
    try:
        params = parse_qs(urlparse(url).query)
        article_id = params.get('article_id', [None])[0]
        office_id = params.get('office_id', [None])[0]
        if article_id and office_id and article_id.isdigit() and office_id.isdigit():
            return f'https://n.news.naver.com/article/{office_id}/{article_id}'
        return None
    except Exception:
        return None

def run_realtime_blog_automation():
    print("🚀 네이버 증권 실시간 속보 기반 칼럼 자동화를 시작합니다...")

    creds = Credentials.from_authorized_user_file('token.json')
    blogger_service = build('blogger', 'v3', credentials=creds)

    print("\n🌐 네이버 증권 실시간 속보를 수집 중입니다...")
    headlines_raw = []
    articles_with_url = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    try:
        url = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        articles = soup.select('dl')
        for article in articles[:15]:
            title_tag = article.select_one('dd.articleSubject a')
            summary_tag = article.select_one('dd.articleSummary')
            if title_tag:
                title_text = title_tag.text.strip()
                article_url = title_tag.get('href', '')
                if article_url and article_url.startswith('/'):
                    article_url = 'https://finance.naver.com' + article_url
                summary_text = summary_tag.text.strip() if summary_tag else ""
                resolved_url = resolve_naver_url(article_url)
                image_url = fetch_article_image(resolved_url) if resolved_url else None
                if resolved_url:
                    articles_with_url.append({'title': title_text, 'url': resolved_url, 'summary': summary_text, 'image': image_url})
                    entry = f"제목: {title_text}\nURL: {resolved_url}"
                    if summary_text:
                        entry += f"\n요약: {summary_text}"
                    headlines_raw.append(entry)
                else:
                    articles_with_url.append({'title': title_text, 'url': '', 'summary': summary_text, 'image': None})
                    entry = f"제목: {title_text}"
                    if summary_text:
                        entry += f"\n요약: {summary_text}"
                    headlines_raw.append(entry)
        print(f"✅ 실시간 속보 {len(headlines_raw)}건 수집 완료")
    except Exception as e:
        print(f"⚠️ 실시간 속보 수집 실패 (사유: {e})")

    if not headlines_raw:
        try:
            print("🔄 주요뉴스 페이지로 재시도 중...")
            url2 = "https://finance.naver.com/news/mainnews.naver"
            resp2 = requests.get(url2, headers=headers, timeout=10)
            soup2 = BeautifulSoup(resp2.text, 'html.parser')
            items2 = soup2.select('ul.newsList li dl dt a')
            for a in items2[:15]:
                if a.text.strip():
                    article_url = a.get('href', '')
                    if article_url and article_url.startswith('/'):
                        article_url = 'https://finance.naver.com' + article_url
                    resolved_url = resolve_naver_url(article_url)
                    image_url = fetch_article_image(resolved_url) if resolved_url else None
                    articles_with_url.append({'title': a.text.strip(), 'url': resolved_url or '', 'summary': '', 'image': image_url})
                    entry = f"제목: {a.text.strip()}"
                    if resolved_url:
                        entry += f"\nURL: {resolved_url}"
                    headlines_raw.append(entry)
            print(f"✅ 주요뉴스 {len(headlines_raw)}건 수집 완료")
        except Exception as e2:
            print(f"⚠️ 주요뉴스 수집도 실패 (사유: {e2})")

    if not headlines_raw:
        print("❌ 뉴스 수집 완전 실패. 종료합니다.")
        send_telegram("❌ 블로그 자동화 실패\n뉴스 수집에 실패했습니다.")
        return

    telegram_news = "📰 <b>오늘의 네이버 증권 실시간 속보</b>\n\n"
    for i, h in enumerate(headlines_raw, 1):
        first_line = h.split('\n')[0].replace('제목: ', '')
        telegram_news += f"{i}. {first_line}\n"
    send_telegram(telegram_news)

    news_block = "\n\n".join(headlines_raw)
    print(f"\n📋 수집된 속보 목록:\n{news_block}\n")

    print("🤖 제미나이가 실시간 속보를 분석하여 글을 작성 중입니다...")

    prompt = f"""
당신은 경제·금융 전문 저널리스트입니다.
아래 [오늘의 실시간 속보]를 분석하여 가장 임팩트 있는 이슈를 중심으로 글을 작성하세요.

🚨 [팩트 원칙]
과거 학습 데이터의 수치나 사건을 절대 지어내지 마세요.
반드시 아래 [오늘의 실시간 속보]에 있는 내용만을 근거로 작성하세요.
속보에 없는 내용, 기업 연혁·사업 설명·배경 설명은 일절 작성하지 마세요.

[오늘의 실시간 속보]
{news_block}

[이슈 선정 기준]
- 위 속보들 중 가장 많이 반복되거나 연관된 이슈를 핵심 주제로 선정하세요.
- 단일 종목 이슈보다 시장 전반에 영향을 주는 이슈를 우선하세요.
- 선정한 핵심 이슈와 연관된 속보들을 엮어 하나의 흐름으로 서술하세요.

[제목 규칙]
- 선정한 핵심 이슈와 가장 직결된 속보 제목 하나를 골라 뉘앙스만 바꿔 재작성하세요.
- 원문을 그대로 복사하지 마세요. 단어·어순·표현을 바꿔 클릭을 유도하세요.
- 속보에 등장하는 숫자·고유명사는 그대로 유지하세요.
- "코스닥", "코스피", "시장", "증시" 등 지수·시장 전체를 지칭하는 단어는 제목에 절대 사용하지 마세요.
- 제목에 느낌표(!)는 사용하지 마세요.

[라벨 규칙]
아래 3개 중 이번 글의 핵심 이슈에 가장 적합한 라벨 1개만 선택하세요.
- 시장 이슈: 금리, 환율, 지수, 거시경제, 정책 등 시장 전반에 영향을 주는 이슈
- 실시간 속보: 돌발 이벤트, 긴급 공시, 속보성 단일 사건
- Column: 특정 기업·종목 중심의 분석성 내용
반드시 아래 형식으로 응답 맨 끝에 추가하세요.
[LABEL]라벨명[/LABEL]

[문체 규칙]
- 문어체로 작성하세요. (~이다, ~한다, ~했다, ~전망이다)
- 구어체(~거든요, ~이에요, ~해요)는 절대 사용하지 마세요.
- 속보 내용을 단순 나열하지 말고 흐름에 맞게 해석·조합하여 서술하세요.
- 전문 용어는 괄호로 풀어쓰세요. 예: FOMC(미국 연방공개시장위원회)
- 칼럼니스트 시선, 총평, 결론 섹션은 절대 작성하지 마세요.
- Markdown 기호(**, #, -, *)는 절대 사용하지 마세요.

[AI 티 제거 규칙 - 반드시 준수]
- "~것으로 추정된다", "~것으로 보인다", "~것으로 분석된다" 사용 금지
- "~것으로 관측된다", "~것으로 파악된다", "~것으로 해석된다" 사용 금지
- "~양상을 보이고 있다", "~움직임을 보이고 있다" 사용 금지
- "이는 ~을 시사한다", "~에 기인한다" 사용 금지
- "단순히 ~이 아니라", "복합적인 요인" 사용 금지
- 불확실한 추측성 표현 대신 속보에 근거한 단정적 사실 문장으로 작성하세요.
- 같은 문장 구조를 반복하지 마세요. 단락마다 문장 길이와 구조를 다양하게 구성하세요.
- 각 문장은 구체적인 수치·인물·기관명을 포함해 생동감 있게 작성하세요.

[구조 규칙]
- 전체를 3~4개 챕터로 구성하세요.
- 각 챕터는 아래 형식으로 시작하세요.
  <h3 style="margin-top:2em;">① 챕터 제목</h3>
- 각 챕터당 본문 단락을 최소 3개 이상 작성하세요. 단락 하나가 3~5문장 분량이 되도록 충분히 서술하세요.
- 챕터 내 핵심 문장 첫 줄은 <strong> 태그로 굵게 처리하세요.
- 독자가 반드시 알아야 할 1~2줄은 아래 형식으로 하이라이트 처리하세요.
  <span style="background-color:#b2f0e8; padding:2px 6px;">강조 문장</span>
- 세부 항목이 2개 이상이면 <ul style="margin-top:0.8em; margin-bottom:0.8em;"><li style="margin-bottom:0.5em;">항목</li></ul> 형식으로 나열하세요. 각 항목도 1~2문장으로 충분히 설명하세요.
- 단락과 단락 사이는 반드시 <p style="margin-bottom:1.4em;"> 태그로 감싸 충분한 여백을 확보하세요.
- 수치·날짜 부연설명은 <small style="color:#666;">*내용</small> 형식을 사용하세요.
- 표(table)를 생성할 경우 반드시 첫 번째 헤더 행(thead > tr)의 각 셀(th)에 style="text-align:center" 속성을 적용하세요.
- 전체 글자 수는 최소 1,500자 이상이 되도록 작성하세요.
- 본문 맨 끝에 반드시 아래 면책조항 HTML을 그대로 삽입하세요. 내용 수정 금지.
<div style="margin-top:2em;padding:20px 24px;background:#fafafa;border-radius:12px;border:1px solid #e2e8f0;">
  <p style="margin:0 0 8px 0;font-size:13px;font-weight:700;color:#64748b;">투자 유의사항</p>
  <p style="margin:0;font-size:13px;color:#94a3b8;line-height:1.8;">본 콘텐츠는 정보 제공 목적으로 작성되었으며, 투자 권유 또는 종목 추천이 아닙니다. 본문에 포함된 수치·지수·주가 등은 뉴스 보도 시점 기준이며, 시장 상황에 따라 실시간으로 변동되므로 실제 현재 수치와 다를 수 있습니다. 투자 결정에 따른 손익은 투자자 본인에게 귀속되며, 본 블로그는 이에 대한 법적 책임을 지지 않습니다.</p>
</div>

[링크 규칙]
- 본문에 <a> 태그나 URL 링크를 절대 삽입하지 마세요. 관련기사 링크는 별도로 처리됩니다.

[응답 형식]
반드시 아래 형식으로 시작하세요.
[TITLE]제목[/TITLE]
이후 본문 HTML을 작성하세요.
본문 맨 끝에 반드시 아래를 추가하세요.
[LABEL]라벨명[/LABEL]
"""

    blog_content = ""
    for attempt in range(5):
        try:
            response = gemini_client.models.generate_content(model=model_name, contents=prompt)
            blog_content = response.text
            print(f"✅ 제미나이 글 작성 완료!")
            break
        except Exception as e:
            print(f"⚠️ Gemini 호출 실패 ({attempt+1}/5): {e}")
            if attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"  {wait}초 후 재시도...")
                time.sleep(wait)
            else:
                send_telegram("❌ 블로그 자동화 실패\nGemini 글 작성에 실패했습니다.")
                raise

    title_match = re.search(r'\[TITLE\](.*?)\[/TITLE\]', blog_content)
    label_match = re.search(r'\[LABEL\](.*?)\[/LABEL\]', blog_content)

    title = title_match.group(1).strip() if title_match else "오늘의 증권 실시간 이슈 분석"
    label_raw = label_match.group(1).strip() if label_match else "시장 이슈"

    valid_labels = ['시장 이슈', '실시간 속보', 'Column']
    label = label_raw if label_raw in valid_labels else '시장 이슈'

    body = re.sub(r'\[TITLE\].*?\[/TITLE\]\n?', '', blog_content)
    body = re.sub(r'\[LABEL\].*?\[/LABEL\]\n?', '', body).strip()

    body = strip_all_links(body)
    body = insert_ad_after_first_chapter(body, AD_AUTORELAXED)

    rep_image = build_representative_image(articles_with_url)
    cta = build_top_cta(title)
    related = build_related_articles_section(articles_with_url)

    body = rep_image + cta + AD_DISPLAY + body
    if related:
        body += '\n' + related + '\n' + AD_DISPLAY
    else:
        body += '\n' + AD_DISPLAY

    print(f"📝 글 제목: {title}")
    print(f"🏷️ 라벨: {label}")

    print("🌐 블로그스팟에 글을 전송하는 중...")
    post_data = {'title': title, 'content': body, 'labels': [label]}
    request = blogger_service.posts().insert(blogId=BLOG_ID, body=post_data, isDraft=True)
    result = request.execute()
    print("🎉 완료! 블로그스팟 관리자 페이지의 '임시 저장물' 보관함에 등록되었습니다.")

    post_url = result.get('url', '블로그 확인 필요')
    send_telegram(
        f"✅ <b>블로그 자동 발행 완료</b>\n\n"
        f"📝 제목: {title}\n"
        f"🏷️ 라벨: {label}\n\n"
        f"🔗 확인: {post_url}"
    )

if __name__ == '__main__':
    run_realtime_blog_automation()
