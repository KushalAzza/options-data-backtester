#!/usr/bin/env python3
"""
Flask web application for viewing Nifty Options Backtest Results
"""

from flask import Flask, render_template, jsonify
import json
import os
from datetime import datetime, timedelta
from datetime import datetime, timedelta

app = Flask(__name__)

# Configuration
RESULTS_JSON = "backtest_results.json"
NIFTY_INTRADAY_JSON = "data/nifty_intraday_price.json"


def load_results():
    """Load backtest results from JSON file"""
    if not os.path.exists(RESULTS_JSON):
        return None
    
    with open(RESULTS_JSON, 'r') as f:
        return json.load(f)


def prepare_trade_rows(results):
    """Prepare trade rows with cumulative P&L for display"""
    rows = []
    cumulative_sum = 0
    
    for r in results:
        entry_time_str = r['entry_time'].split(' ')[1][:5]
        entry_reason = r.get('entry_reason', 'NORMAL')
        
        # Skip trades that didn't enter due to VIX threshold - show as single row
        if entry_reason == 'VIX_THRESHOLD_EXCEEDED':
            rows.append({
                'date': r['date'],
                'entry_time': entry_time_str,
                'exit_time': entry_time_str,  # Same as entry since no trade occurred
                'entry_reason': entry_reason,
                'exit_reason': 'N/A',
                'stopped': False,
                'expiry_date': r.get('expiry_date'),
                'vix_at_entry': r.get('vix_at_entry'),
                'vix_at_exit': r.get('vix_at_exit'),
                'nifty_entry_price': r['nifty_entry_price'],
                'nifty_exit_price': r['nifty_exit_price'],
                'option_type': 'SKIP',
                'strike': None,
                'entry_price': None,
                'exit_price': None,
                'pnl': 0.0,
                'cumulative_pnl': cumulative_sum
            })
            continue
        
        # CE row - use individual exit time and reason
        ce_exit_time_str = r.get('ce_exit_time', r['exit_time']).split(' ')[1][:5] if r.get('ce_exit_time') else entry_time_str
        ce_exit_reason = r.get('ce_exit_reason', 'SCHEDULED_EXIT')
        ce_stopped = r.get('ce_stopped', False)
        
        cumulative_sum += r['ce_pnl']
        rows.append({
            'date': r['date'],
            'entry_time': entry_time_str,
            'exit_time': ce_exit_time_str,
            'entry_reason': entry_reason,
            'exit_reason': ce_exit_reason,
            'stopped': ce_stopped,
            'expiry_date': r.get('expiry_date'),
            'vix_at_entry': r.get('vix_at_entry'),
            'vix_at_exit': r.get('vix_at_exit'),
            'nifty_entry_price': r['nifty_entry_price'],
            'nifty_exit_price': r['nifty_exit_price'],
            'option_type': 'CE',
            'strike': r['ce_strike'],
            'entry_price': r['ce_entry_price'],
            'exit_price': r['ce_exit_price'],
            'pnl': r['ce_pnl'],
            'cumulative_pnl': cumulative_sum
        })
        
        # PE row - use individual exit time and reason
        pe_exit_time_str = r.get('pe_exit_time', r['exit_time']).split(' ')[1][:5] if r.get('pe_exit_time') else entry_time_str
        pe_exit_reason = r.get('pe_exit_reason', 'SCHEDULED_EXIT')
        pe_stopped = r.get('pe_stopped', False)
        
        cumulative_sum += r['pe_pnl']
        rows.append({
            'date': r['date'],
            'entry_time': entry_time_str,
            'exit_time': pe_exit_time_str,
            'entry_reason': entry_reason,
            'exit_reason': pe_exit_reason,
            'stopped': pe_stopped,
            'expiry_date': r.get('expiry_date'),
            'vix_at_entry': r.get('vix_at_entry'),
            'vix_at_exit': r.get('vix_at_exit'),
            'nifty_entry_price': r['nifty_entry_price'],
            'nifty_exit_price': r['nifty_exit_price'],
            'option_type': 'PE',
            'strike': r['pe_strike'],
            'entry_price': r['pe_entry_price'],
            'exit_price': r['pe_exit_price'],
            'pnl': r['pe_pnl'],
            'cumulative_pnl': cumulative_sum
        })
    
    return rows


@app.route('/')
def index():
    """Main page displaying backtest results"""
    data = load_results()
    if not data:
        return "No backtest results found. Please run run_backtest.py first.", 404
    
    # Prepare trade rows with cumulative P&L
    trade_rows = prepare_trade_rows(data['results'])
    
    return render_template('index.html', data=data, trade_rows=trade_rows)


@app.route('/api/results')
def api_results():
    """API endpoint to get results as JSON"""
    data = load_results()
    if not data:
        return jsonify({"error": "No results found"}), 404
    
    return jsonify(data)


def load_nifty_intraday_data(start_date, end_date):
    """Load and filter Nifty intraday data for the backtest period"""
    if not os.path.exists(NIFTY_INTRADAY_JSON):
        return None
    
    try:
        with open(NIFTY_INTRADAY_JSON, 'r') as f:
            nifty_data = json.load(f)
        
        # Filter data for the backtest period
        # Also include historical data from previous days for EMA calculation
        filtered_data = []
        historical_data = []
        
        # Get start date for historical data lookup (need previous days for EMA)
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
        # Look back up to 10 days for historical data
        for days_back in range(1, 11):
            hist_date = start_date_obj - timedelta(days=days_back)
            hist_date_str = hist_date.strftime("%Y-%m-%d")
            # Skip weekends
            if hist_date.weekday() >= 5:
                continue
            if hist_date_str in nifty_data:
                for entry in nifty_data[hist_date_str]:
                    historical_data.append({
                        'time': entry['time'],
                        'close': entry['close'],
                        'open': entry['open'],
                        'high': entry['high'],
                        'low': entry['low'],
                        'volume': entry.get('volume', 0)
                    })
        
        # Get data for the selected date range
        for date_key in nifty_data:
            if start_date <= date_key <= end_date:
                for entry in nifty_data[date_key]:
                    filtered_data.append({
                        'time': entry['time'],
                        'close': entry['close'],
                        'open': entry['open'],
                        'high': entry['high'],
                        'low': entry['low'],
                        'volume': entry.get('volume', 0)
                    })
        
        # Sort by time
        historical_data.sort(key=lambda x: x['time'])
        filtered_data.sort(key=lambda x: x['time'])
        
        # Return both historical and filtered data
        return {
            'historical': historical_data,
            'data': filtered_data
        }
    except Exception as e:
        print(f"Error loading Nifty data: {e}")
        return None


@app.route('/api/nifty-intraday')
def api_nifty_intraday():
    """API endpoint to get Nifty intraday data for specified date range"""
    from flask import request
    
    # Get date range from query parameters or use backtest results range as default
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # If no dates provided, use backtest results range as default
    if not start_date or not end_date:
        data = load_results()
        if data and data.get('results'):
            dates = [r['date'] for r in data['results']]
            if dates:
                start_date = min(dates)
                end_date = max(dates)
            else:
                return jsonify({"error": "No dates found"}), 404
        else:
            return jsonify({"error": "No results found and no date range provided"}), 404
    
    nifty_data_result = load_nifty_intraday_data(start_date, end_date)
    if not nifty_data_result:
        return jsonify({"error": f"No Nifty data found for date range {start_date} to {end_date}"}), 404
    
    # Load config to get EMA parameters
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        ema_config = config.get('ema_signals', {})
        ema_params = {
            'time_interval': ema_config.get('time_interval', 15),
            'fast_ema': ema_config.get('fast_ema', 9),
            'slow_ema': ema_config.get('slow_ema', 21)
        }
    except:
        ema_params = {
            'time_interval': 15,
            'fast_ema': 9,
            'slow_ema': 21
        }
    
    # Handle both new format (dict with historical and data) and legacy format (array)
    if isinstance(nifty_data_result, dict):
        return jsonify({
            'historical': nifty_data_result.get('historical', []),
            'data': nifty_data_result.get('data', []),
            'ema_params': ema_params
        })
    else:
        # Legacy format - return as data array
        return jsonify({
            'historical': [],
            'data': nifty_data_result,
            'ema_params': ema_params
        })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3003, debug=True)

