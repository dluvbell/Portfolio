import yfinance as yf
import pandas as pd
import json
import os
from datetime import datetime

# 데이터 파일 경로
DB_PATH = 'portfolio.json'

# 피어 그룹 정의 (Server.js 로직 이식)
PEER_GROUPS = {
    # Tech Breakdown
    "Semiconductors": ["NVDA", "TSM", "AVGO", "AMD", "INTC", "QCOM", "TXN", "MU"],
    "Consumer Electronics": ["AAPL", "SONY", "XIACY"],
    "Software-Infrastructure": ["MSFT", "ORCL", "ADBE", "CRM", "PANW", "SNOW"],
    "Internet Content": ["GOOGL", "META", "NFLX", "DASH", "SNAP", "PINS"],
    "Internet Retail": ["AMZN", "BABA", "PDD", "JD", "EBAY", "CHWY"],
    
    # Auto
    "Auto Manufacturers": ["TSLA", "TM", "VOW3.DE", "STLA", "F", "GM", "HMC"],
    
    # Financials Breakdown
    "Financial": ["BRK-B", "V", "MA", "AXP", "MS", "GS", "BLK"], 
    
    # Healthcare Breakdown
    "Drug Manufacturers": ["LLY", "JNJ", "ABBV", "MRK", "PFE", "NVS", "AZN", "BMY"],
    
    # Consumer Defensive Breakdown
    "Discount Stores": ["WMT", "COST", "TGT", "DG", "DLTR"], 
    "Household & Personal Products": ["PG", "CL", "EL", "KMB", "CHD"],
    "Beverages - Non-Alcoholic": ["KO", "PEP", "MNST", "KDP", "CELH"],
    
    # Crypto
    "Crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "DOGE-USD", "ADA-USD"]
}

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

    # 모든 티커 수집 (API 호출 최소화를 위해)
    all_tickers = set()
    for item in portfolio:
        sector = item.get('sector', 'Unknown')
        peers = PEER_GROUPS.get(sector, [item['ticker']])
        if item['ticker'] not in peers:
            peers.append(item['ticker'])
        all_tickers.update(peers)
    
    # 데이터 일괄 다운로드 (속도 향상)
    # '.'을 '-'로 변경 (BRK.B -> BRK-B)
    download_list = [t.replace('.', '-') for t in all_tickers]
    
    print("Downloading data for:", len(download_list), "tickers...")
    try:
        # yfinance 대량 다운로드 (가장 최근 데이터만)
        # info를 가져오는 건 느리므로, price * shares 대신 fast_info 사용 또는
        # 여기서는 단순화를 위해 Ticker 객체 루프를 돌되, 오류 시 패스
        tickers_data = {}
        for t in download_list:
            try:
                # fast_info가 시가총액 가져오기에 빠름
                info = yf.Ticker(t).fast_info
                mkt_cap = info.market_cap
                # 만약 fast_info 실패시 info 시도
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
        
        # 해당 그룹의 시가총액 리스트 생성
        group_stats = []
        for peer in peers:
            p_sym = peer.replace('.', '-')
            cap = tickers_data.get(p_sym, 0)
            group_stats.append({'symbol': peer, 'cap': cap})
        
        # 시총 순 정렬 (내림차순)
        ranked_list = sorted(group_stats, key=lambda x: x['cap'], reverse=True)
        
        # 내 순위 찾기
        my_data = next((x for x in ranked_list if x['symbol'] == item['ticker']), None)
        if not my_data:
            updated_portfolio.append(item)
            continue
            
        my_rank_index = ranked_list.index(my_data)
        my_rank = my_rank_index + 1
        my_cap = my_data['cap']
        
        # 경쟁자(Chaser) 찾기 (Rank + 1)
        chaser_index = my_rank_index + 1
        competitor_str = "None"
        gap_percent = 0.0
        
        if chaser_index < len(ranked_list):
            chaser = ranked_list[chaser_index]
            competitor_str = f"{my_rank + 1}. {chaser['symbol']}"
            if chaser['cap'] > 0:
                # Gap: (나 - 추격자) / 추격자 * 100
                gap_percent = ((my_cap - chaser['cap']) / chaser['cap']) * 100
        else:
            competitor_str = "Last Rank"
            gap_percent = 999.9
            
        # Status Logic (기존 JS 로직 동일 적용)
        limit_rank = 3
        is_rank_dropped = my_rank > limit_rank
        # Gap Critical 조건: 순위 밀림 AND 격차 10% 이상 (JS 로직: isGapCritical 미사용이나 계산은 함)
        
        today_str = datetime.now().isoformat()
        current_status = item.get('status', 'Green')
        yellow_date = item.get('yellowDate')
        
        new_status = current_status
        new_yellow_date = yellow_date
        
        if current_status == 'Green':
            if is_rank_dropped:
                new_status = 'Yellow'
                new_yellow_date = today_str
        elif current_status == 'Yellow':
            if not is_rank_dropped:
                new_status = 'Green'
                new_yellow_date = None
            else:
                # 1년 경과 체크
                if yellow_date:
                    try:
                        y_date = datetime.fromisoformat(yellow_date.replace('Z', ''))
                        # naive datetime 처리
                        if y_date.tzinfo is not None:
                            y_date = y_date.replace(tzinfo=None)
                        
                        diff_days = (datetime.now() - y_date).days
                        if diff_days >= 365:
                            new_status = 'Red'
                    except:
                        pass # 날짜 파싱 에러 시 무시

        # 아이템 업데이트
        item['rank'] = my_rank
        item['gap'] = round(gap_percent, 1)
        item['marketCap'] = f"{my_cap / 1_000_000_000:.1f}B" if my_cap else "N/A"
        item['competitor'] = competitor_str
        item['status'] = new_status
        item['yellowDate'] = new_yellow_date
        
        updated_portfolio.append(item)
        print(f"Updated {ticker}: Rank {my_rank}, Gap {item['gap']}%, Status {new_status}")

    # 저장
    save_portfolio(updated_portfolio)
    print("Portfolio updated successfully.")

if __name__ == "__main__":
    scan_market()