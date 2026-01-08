import yfinance as yf
import json
import os
import requests # 텔레그램 전송용
from datetime import datetime

# 데이터 파일 경로
DB_PATH = 'portfolio.json'

# 환경변수에서 텔레그램 정보 가져오기 (GitHub Secrets)
TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# 피어 그룹 정의
PEER_GROUPS = {
    "Semiconductors": ["NVDA", "TSM", "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU"],
    "Consumer Electronics": ["AAPL", "SONY", "XIACY"],
    "Software-Infrastructure": ["MSFT", "ORCL", "ADBE", "CRM", "PANW", "SNOW"],
    "Internet Content": ["GOOGL", "META", "NFLX", "DASH", "SNAP", "PINS"],
    "Internet Retail": ["AMZN", "BABA", "PDD", "JD", "EBAY", "CHWY"],
    "Auto Manufacturers": ["TSLA", "TM", "VOW3.DE", "STLA", "F", "GM", "HMC"],
    "Financial": ["BRK-B", "V", "MA", "AXP", "MS", "GS", "BLK"], 
    "Drug Manufacturers": ["LLY", "JNJ", "ABBV", "MRK", "PFE", "NVS", "AZN", "BMY"],
    "Discount Stores": ["WMT", "COST", "TGT", "DG", "DLTR"], 
    "Household & Personal Products": ["PG", "CL", "EL", "KMB", "CHD"],
    "Beverages - Non-Alcoholic": ["KO", "PEP", "MNST", "KDP", "CELH"],
    "Crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "DOGE-USD", "ADA-USD"]
}

def send_telegram_message(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print("Telegram Token or Chat ID missing. Skipping notification.")
        return
    
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def load_portfolio():
    if not os.path.exists(DB_PATH):
        return []
    with open(DB_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_portfolio(data):
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def scan_market():
    portfolio = load_portfolio()
    if not portfolio:
        print("No portfolio data found.")
        return

    print("=== Checking Market Data (Unified Limit: Top 3) ===")
    
    updated_portfolio = []
    alert_messages = [] # 알림 모음

    # 모든 티커 수집
    all_tickers = set()
    for item in portfolio:
        sector = item.get('sector', 'Unknown')
        peers = PEER_GROUPS.get(sector, [item['ticker']])
        if item['ticker'] not in peers:
            peers.append(item['ticker'])
        all_tickers.update(peers)
    
    # 데이터 일괄 다운로드
    download_list = [t.replace('.', '-') for t in all_tickers]
    print("Downloading data for:", len(download_list), "tickers...")
    
    tickers_data = {}
    try:
        for t in download_list:
            try:
                info = yf.Ticker(t).fast_info
                mkt_cap = info.market_cap
                if mkt_cap is None:
                    mkt_cap = yf.Ticker(t).info.get('marketCap', 0)
                tickers_data[t] = mkt_cap
            except Exception as e:
                print(f"Failed to fetch {t}: {e}")
                tickers_data[t] = 0
    except Exception as e:
        print(f"Major download error: {e}")
        return

    # 포트폴리오 업데이트 루프
    for item in portfolio:
        ticker = item['ticker'].replace('.', '-')
        sector = item.get('sector', 'Unknown')
        
        peers = PEER_GROUPS.get(sector, [ticker])
        if ticker not in peers:
            peers.append(ticker)
        
        # 그룹 시가총액 비교
        group_stats = []
        for peer in peers:
            p_sym = peer.replace('.', '-')
            cap = tickers_data.get(p_sym, 0)
            group_stats.append({'symbol': peer, 'cap': cap})
        
        ranked_list = sorted(group_stats, key=lambda x: x['cap'], reverse=True)
        
        my_data = next((x for x in ranked_list if x['symbol'] == item['ticker']), None)
        if not my_data:
            updated_portfolio.append(item)
            continue
            
        my_rank_index = ranked_list.index(my_data)
        my_rank = my_rank_index + 1
        my_cap = my_data['cap']
        
        # 경쟁자(Chaser) 찾기
        chaser_index = my_rank_index + 1
        competitor_str = "None"
        gap_percent = 0.0
        
        if chaser_index < len(ranked_list):
            chaser = ranked_list[chaser_index]
            competitor_str = f"{my_rank + 1}. {chaser['symbol']}"
            if chaser['cap'] > 0:
                gap_percent = ((my_cap - chaser['cap']) / chaser['cap']) * 100
        else:
            competitor_str = "Last Rank"
            gap_percent = 999.9
            
        # --- [Logic Update] Status Determination ---
        # 1. 기초 데이터 판단
        limit_rank = 3
        is_rank_dropped = my_rank > limit_rank
        is_gap_critical = (is_rank_dropped and gap_percent >= 10.0) # Gap 10% 이상 & 순위 밀림

        # 2. 순간 상태(Instant Status) 결정
        instant_status = 'Green'
        if is_rank_dropped:
            if is_gap_critical:
                instant_status = 'Red'
            else:
                instant_status = 'Yellow'
        
        # 3. 지속 기간(Duration) 및 최종 상태(Final Status) 결정
        old_status = item.get('status', 'Green')
        current_red_date = item.get('redDate') # 기존에 저장된 Red 시작일
        
        final_status = instant_status
        final_red_date = None

        if instant_status == 'Red':
            # 레드 구역 진입 혹은 유지 중
            if current_red_date:
                # 이미 레드였음 -> 기간 체크
                try:
                    r_date = datetime.fromisoformat(current_red_date.replace('Z', ''))
                    diff_days = (datetime.now() - r_date).days
                    
                    final_red_date = current_red_date # 시작일 유지
                    
                    if diff_days >= 365: # 4분기(1년) 이상
                        final_status = 'Black 2'
                    elif diff_days >= 180: # 2분기(6개월) 이상
                        final_status = 'Black 1'
                    else:
                        final_status = 'Red'
                except:
                    # 날짜 에러 시 리셋
                    final_red_date = datetime.now().isoformat()
                    final_status = 'Red'
            else:
                # 레드로 처음 진입
                final_red_date = datetime.now().isoformat()
                final_status = 'Red'
        else:
            # Green이나 Yellow로 돌아오면 Red Timer 리셋 (살아남음)
            final_red_date = None
            final_status = instant_status

        # 4. 알림 로직 (상태가 변했을 때만)
        if old_status != final_status:
            icon = "🟢"
            if final_status == "Yellow": icon = "🟡"
            if final_status == "Red": icon = "🔴"
            if final_status == "Black 1": icon = "⚫1️⃣"
            if final_status == "Black 2": icon = "⚫2️⃣"
            
            msg = f"{icon} *{item['ticker']} Status Change*\n"
            msg += f"From: {old_status} -> To: *{final_status}*\n"
            msg += f"Rank: {my_rank} (Gap: {gap_percent:.1f}%)"
            alert_messages.append(msg)

        # 아이템 업데이트
        item['rank'] = my_rank
        item['gap'] = round(gap_percent, 1)
        item['marketCap'] = f"{my_cap / 1_000_000_000:.1f}B" if my_cap else "N/A"
        item['competitor'] = competitor_str
        item['status'] = final_status
        item['redDate'] = final_red_date # redDate 필드 저장 (기존 yellowDate 대체/병행)
        
        # 기존 yellowDate 필드는 호환성을 위해 남겨두거나 null 처리 (여기선 혼동 방지 위해 놔둠)
        
        updated_portfolio.append(item)
        print(f"Updated {ticker}: Rank {my_rank}, Gap {item['gap']}%, Status {final_status}")

    # 저장
    save_portfolio(updated_portfolio)
    
    # 알림 전송 (한 번에 묶어서)
    if alert_messages:
        full_msg = "📢 *Titans Update Alert*\n\n" + "\n\n".join(alert_messages)
        send_telegram_message(full_msg)
        print("Telegram notification sent.")
    else:
        print("No status changes detected.")

if __name__ == "__main__":
    scan_market()
