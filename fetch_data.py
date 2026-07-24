"""
금융시장 위험 감지 대시보드 - 데이터 수집 스크립트
GitHub Actions에서 주기적으로 실행하여 data.json을 생성합니다.

데이터 소스:
- FRED (S&P500, USD/KRW, 10Y금리, VIX, M2, WTI, Gold)
- CoinGecko (Bitcoin)
- ECOS 한국은행 (KOSPI)
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# API Keys (GitHub Secrets에서 주입)
FRED_KEY = os.environ.get('FRED_API_KEY', 'b7defa04bf2b8e6a3b80e7d0209024e3')
ECOS_KEY = os.environ.get('ECOS_API_KEY', 'LELDVS32GE3X5IMIGJK1')


def fetch_json(url, timeout=15):
    """URL에서 JSON 데이터를 가져옵니다."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"  [ERROR] {url[:80]}... → {e}")
        return None


def fetch_fred(series_id, limit=5):
    """FRED API에서 시계열 데이터를 가져옵니다."""
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}&api_key={FRED_KEY}"
        f"&file_type=json&sort_order=desc&limit={limit}"
    )
    data = fetch_json(url)
    if not data or 'observations' not in data:
        return None

    observations = [
        {'date': o['date'], 'value': float(o['value'])}
        for o in data['observations']
        if o['value'] != '.'
    ]
    observations.reverse()
    return observations


def fetch_coingecko_btc():
    """CoinGecko에서 Bitcoin 가격을 가져옵니다."""
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=2&interval=daily"
    data = fetch_json(url)
    if not data or 'prices' not in data:
        return None

    prices = [
        {'date': datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc).strftime('%Y-%m-%d'), 'value': p[1]}
        for p in data['prices']
    ]
    return prices


def fetch_ecos_kospi():
    """한국은행 ECOS에서 KOSPI 데이터를 가져옵니다."""
    today = datetime.now().strftime('%Y%m%d')
    week_ago = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}"
        f"/json/kr/1/10/802Y001/D/{week_ago}/{today}/0001000"
    )
    data = fetch_json(url)
    if not data:
        return None

    stat = data.get('StatisticSearch', {})
    rows = stat.get('row', [])
    if not rows:
        return None

    return [
        {'date': r['TIME'], 'value': float(r['DATA_VALUE'])}
        for r in rows
        if r.get('DATA_VALUE')
    ]


def calc_change(observations):
    """최근 2개 데이터로 전일대비 변동률을 계산합니다."""
    if not observations or len(observations) < 2:
        return {'current': observations[-1]['value'] if observations else None, 'previous': None, 'change_pct': None}

    current = observations[-1]['value']
    previous = observations[-2]['value']
    if previous == 0:
        change_pct = 0
    else:
        change_pct = round(((current - previous) / previous) * 100, 2)

    return {'current': current, 'previous': previous, 'change_pct': change_pct}


def main():
    print(f"=== 금융 데이터 수집 시작: {datetime.now().isoformat()} ===\n")

    result = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'indicators': {}
    }

    # FRED 데이터
    fred_series = {
        'sp500': {'id': 'SP500', 'name': 'S&P 500'},
        'fx': {'id': 'DEXKOUS', 'name': 'USD/KRW'},
        'bond': {'id': 'DGS10', 'name': 'US 10Y Treasury'},
        'vix': {'id': 'VIXCLS', 'name': 'VIX'},
        'm2': {'id': 'M2SL', 'name': 'M2 Money Supply'},
        'oil': {'id': 'DCOILWTICO', 'name': 'WTI Crude Oil'},
    }

    for key, info in fred_series.items():
        print(f"  Fetching FRED/{info['id']}...", end=' ')
        observations = fetch_fred(info['id'])
        if observations:
            stats = calc_change(observations)
            result['indicators'][key] = {
                'name': info['name'],
                'source': 'FRED',
                'series_id': info['id'],
                'current': stats['current'],
                'previous': stats['previous'],
                'change_pct': stats['change_pct'],
                'date': observations[-1]['date'],
                'history': observations
            }
            print(f"✓ {stats['current']} ({'+' if (stats['change_pct'] or 0) >= 0 else ''}{stats['change_pct']}%)")
        else:
            print("✗ FAILED")

    # CoinGecko BTC
    print(f"  Fetching CoinGecko/BTC...", end=' ')
    btc_data = fetch_coingecko_btc()
    if btc_data:
        stats = calc_change(btc_data)
        result['indicators']['btc'] = {
            'name': 'Bitcoin',
            'source': 'CoinGecko',
            'current': stats['current'],
            'previous': stats['previous'],
            'change_pct': stats['change_pct'],
            'date': btc_data[-1]['date'],
            'history': btc_data
        }
        print(f"✓ ${stats['current']:,.0f} ({'+' if (stats['change_pct'] or 0) >= 0 else ''}{stats['change_pct']}%)")
    else:
        print("✗ FAILED")

    # CoinGecko Gold (Tether Gold = 1oz 실물 금 가격 추종)
    print(f"  Fetching CoinGecko/Gold...", end=' ')
    gold_json = fetch_json("https://api.coingecko.com/api/v3/simple/price?ids=tether-gold&vs_currencies=usd&include_24hr_change=true")
    if gold_json and 'tether-gold' in gold_json:
        gold_price = gold_json['tether-gold']['usd']
        gold_change = round(gold_json['tether-gold'].get('usd_24h_change', 0), 2)
        gold_prev = round(gold_price / (1 + gold_change / 100), 2)
        result['indicators']['gold'] = {
            'name': 'Gold ($/oz)',
            'source': 'CoinGecko',
            'current': gold_price,
            'previous': gold_prev,
            'change_pct': gold_change,
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'history': [{'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'), 'value': gold_price}]
        }
        print(f"✓ ${gold_price:,.0f} ({'+' if gold_change >= 0 else ''}{gold_change}%)")
    else:
        print("✗ FAILED")

    # ECOS KOSPI
    print(f"  Fetching ECOS/KOSPI...", end=' ')
    kospi_data = fetch_ecos_kospi()
    if kospi_data:
        stats = calc_change(kospi_data)
        result['indicators']['kospi'] = {
            'name': 'KOSPI',
            'source': 'ECOS',
            'current': stats['current'],
            'previous': stats['previous'],
            'change_pct': stats['change_pct'],
            'date': kospi_data[-1]['date'],
            'history': kospi_data
        }
        print(f"✓ {stats['current']:,.0f} ({'+' if (stats['change_pct'] or 0) >= 0 else ''}{stats['change_pct']}%)")
    else:
        print("✗ FAILED")

    # JSON 저장
    output_path = 'data.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n=== 완료: {output_path} 저장 ({len(result['indicators'])}개 지표) ===")


if __name__ == '__main__':
    main()
