#!/usr/bin/env python3
"""
Flask web application for viewing Nifty Options Backtest Results
"""

from flask import Flask, render_template, jsonify, request
import json
import os
import subprocess
from datetime import datetime, timedelta

app = Flask(__name__)

# Configuration
RESULTS_JSON = "backtest_results.json"
NIFTY_INTRADAY_JSON = "data/nifty_intraday_price.json"
VIX_INTRADAY_JSON = "data/india_vix_intraday_price.json"


def load_results():
    """Load backtest results from JSON file"""
    if not os.path.exists(RESULTS_JSON):
        return None
    
    with open(RESULTS_JSON, 'r') as f:
        return json.load(f)


def get_ema_values_at_time(nifty_data, date_str, time_str):
    """Get Nifty and EMA values at a specific time from nifty data"""
    if not nifty_data or date_str not in nifty_data:
        return None, None, None
    
    # time_str is in format "HH:MM:SS" or full datetime string
    if ' ' in time_str:
        time_str = time_str.split(' ')[1]  # Extract time part
    
    for entry in nifty_data[date_str]:
        if entry.get('time', '').endswith(time_str):
            return entry.get('close'), entry.get('fast_ema'), entry.get('slow_ema')
    return None, None, None


def format_entry_reason(entry_reason, nifty, fast_ema, slow_ema, vix=None, option_type=None, nifty_data=None, date_str=None, entry_time_str=None):
    """Format entry reason with nifty and EMA values"""
    # For EMA_MIXED, show BEARISH for CE and BULLISH for PE with values at their entry time
    if entry_reason == 'EMA_MIXED' and option_type and nifty_data and date_str and entry_time_str:
        leg_nifty, leg_fast_ema, leg_slow_ema = get_ema_values_at_time(nifty_data, date_str, entry_time_str)
        if leg_nifty is not None and leg_fast_ema is not None and leg_slow_ema is not None:
            nifty = leg_nifty
            fast_ema = leg_fast_ema
            slow_ema = leg_slow_ema
            
            if option_type == 'CE':
                # Show as BEARISH for CE - always show all relationships
                signs = []
                if fast_ema < slow_ema:
                    signs.append("F<S")
                elif fast_ema > slow_ema:
                    signs.append("F>S")
                else:
                    signs.append("F=S")
                if nifty < fast_ema:
                    signs.append("N<F")
                elif nifty > fast_ema:
                    signs.append("N>F")
                else:
                    signs.append("N=F")
                if nifty < slow_ema:
                    signs.append("N<S")
                elif nifty > slow_ema:
                    signs.append("N>S")
                else:
                    signs.append("N=S")
                sign_str = ", ".join(signs) if signs else ""
                return f"BEARISH (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
            elif option_type == 'PE':
                # Show as BULLISH for PE - always show all relationships
                signs = []
                if fast_ema < slow_ema:
                    signs.append("F<S")
                elif fast_ema > slow_ema:
                    signs.append("F>S")
                else:
                    signs.append("F=S")
                if nifty < fast_ema:
                    signs.append("N<F")
                elif nifty > fast_ema:
                    signs.append("N>F")
                else:
                    signs.append("N=F")
                if nifty < slow_ema:
                    signs.append("N<S")
                elif nifty > slow_ema:
                    signs.append("N>S")
                else:
                    signs.append("N=S")
                sign_str = ", ".join(signs) if signs else ""
                return f"BULLISH (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
    
    if entry_reason == 'EMA_BULLISH':
        if fast_ema and slow_ema:
            # BULLISH: always show all relationships
            signs = []
            if fast_ema < slow_ema:
                signs.append("F<S")
            elif fast_ema > slow_ema:
                signs.append("F>S")
            else:
                signs.append("F=S")
            if nifty < fast_ema:
                signs.append("N<F")
            elif nifty > fast_ema:
                signs.append("N>F")
            else:
                signs.append("N=F")
            if nifty < slow_ema:
                signs.append("N<S")
            elif nifty > slow_ema:
                signs.append("N>S")
            else:
                signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"BULLISH (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        return f"BULLISH (N:{nifty:.2f})"
    elif entry_reason == 'EMA_BEARISH':
        if fast_ema and slow_ema:
            # BEARISH: always show all relationships
            signs = []
            if fast_ema < slow_ema:
                signs.append("F<S")
            elif fast_ema > slow_ema:
                signs.append("F>S")
            else:
                signs.append("F=S")
            if nifty < fast_ema:
                signs.append("N<F")
            elif nifty > fast_ema:
                signs.append("N>F")
            else:
                signs.append("N=F")
            if nifty < slow_ema:
                signs.append("N<S")
            elif nifty > slow_ema:
                signs.append("N>S")
            else:
                signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"BEARISH (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        return f"BEARISH (N:{nifty:.2f})"
    elif entry_reason == 'EMA_NEUTRAL':
        if fast_ema and slow_ema:
            # NEUTRAL: always show all relationships
            signs = []
            if abs(fast_ema - slow_ema) < 5:  # Close enough to be considered equal
                signs.append("F≈S")
            elif fast_ema > slow_ema:
                signs.append("F>S")
            else:
                signs.append("F<S")
            if nifty < fast_ema:
                signs.append("N<F")
            elif nifty > fast_ema:
                signs.append("N>F")
            else:
                signs.append("N=F")
            if nifty < slow_ema:
                signs.append("N<S")
            elif nifty > slow_ema:
                signs.append("N>S")
            else:
                signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"NEUTRAL (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        return f"NEUTRAL (N:{nifty:.2f})"
    elif entry_reason == 'EMA_MIXED':
        if fast_ema and slow_ema:
            # MIXED: always show all relationships
            signs = []
            if fast_ema > slow_ema:
                signs.append("F>S")
            elif fast_ema < slow_ema:
                signs.append("F<S")
            else:
                signs.append("F=S")
            if nifty > fast_ema:
                signs.append("N>F")
            elif nifty < fast_ema:
                signs.append("N<F")
            else:
                signs.append("N=F")
            if nifty > slow_ema:
                signs.append("N>S")
            elif nifty < slow_ema:
                signs.append("N<S")
            else:
                signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"MIXED (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        return f"MIXED (N:{nifty:.2f})"
    elif entry_reason in ['RE_BULL', 'RE_BEAR', 'RE_MIXED', 'RE_ENTRY']:
        # Handle re-entry reasons
        if entry_reason == 'RE_BULL':
            if fast_ema and slow_ema:
                signs = []
                if fast_ema > slow_ema:
                    signs.append("F>S")
                elif fast_ema < slow_ema:
                    signs.append("F<S")
                else:
                    signs.append("F=S")
                if nifty:
                    if nifty < fast_ema:
                        signs.append("N<F")
                    elif nifty > fast_ema:
                        signs.append("N>F")
                    else:
                        signs.append("N=F")
                    if nifty < slow_ema:
                        signs.append("N<S")
                    elif nifty > slow_ema:
                        signs.append("N>S")
                    else:
                        signs.append("N=S")
                sign_str = ", ".join(signs) if signs else ""
                return f"RE_BULL (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
            return f"RE_BULL (N:{nifty:.2f})"
        elif entry_reason == 'RE_BEAR':
            if fast_ema and slow_ema:
                signs = []
                if fast_ema > slow_ema:
                    signs.append("F>S")
                elif fast_ema < slow_ema:
                    signs.append("F<S")
                else:
                    signs.append("F=S")
                if nifty:
                    if nifty < fast_ema:
                        signs.append("N<F")
                    elif nifty > fast_ema:
                        signs.append("N>F")
                    else:
                        signs.append("N=F")
                    if nifty < slow_ema:
                        signs.append("N<S")
                    elif nifty > slow_ema:
                        signs.append("N>S")
                    else:
                        signs.append("N=S")
                sign_str = ", ".join(signs) if signs else ""
                return f"RE_BEAR (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
            return f"RE_BEAR (N:{nifty:.2f})"
        elif entry_reason == 'RE_MIXED':
            if fast_ema and slow_ema:
                signs = []
                if fast_ema > slow_ema:
                    signs.append("F>S")
                elif fast_ema < slow_ema:
                    signs.append("F<S")
                else:
                    signs.append("F=S")
                if nifty:
                    if nifty > fast_ema:
                        signs.append("N>F")
                    elif nifty < fast_ema:
                        signs.append("N<F")
                    else:
                        signs.append("N=F")
                    if nifty > slow_ema:
                        signs.append("N>S")
                    elif nifty < slow_ema:
                        signs.append("N<S")
                    else:
                        signs.append("N=S")
                sign_str = ", ".join(signs) if signs else ""
                return f"RE_MIXED (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
            return f"RE_MIXED (N:{nifty:.2f})"
        else:  # RE_ENTRY fallback
            if fast_ema and slow_ema:
                signs = []
                if fast_ema > slow_ema:
                    signs.append("F>S")
                elif fast_ema < slow_ema:
                    signs.append("F<S")
                else:
                    signs.append("F=S")
                if nifty:
                    if nifty < fast_ema:
                        signs.append("N<F")
                    elif nifty > fast_ema:
                        signs.append("N>F")
                    else:
                        signs.append("N=F")
                    if nifty < slow_ema:
                        signs.append("N<S")
                    elif nifty > slow_ema:
                        signs.append("N>S")
                    else:
                        signs.append("N=S")
                sign_str = ", ".join(signs) if signs else ""
                return f"RE_ENTRY (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
            return f"RE_ENTRY (N:{nifty:.2f})"
    elif entry_reason == 'VIX_THRESHOLD_EXCEEDED':
        if vix:
            return f"VIX_THRESHOLD_EXCEEDED (VIX:{vix:.2f} > 100)"
        return "VIX_THRESHOLD_EXCEEDED"
    else:  # Fallback for any other reason (e.g. non-EMA modes)
        if fast_ema and slow_ema:
            signs = []
            if fast_ema > slow_ema:
                signs.append("F>S")
            elif fast_ema < slow_ema:
                signs.append("F<S")
            else:
                signs.append("F=S")
            if nifty:
                if nifty < fast_ema:
                    signs.append("N<F")
                elif nifty > fast_ema:
                    signs.append("N>F")
                else:
                    signs.append("N=F")
                if nifty < slow_ema:
                    signs.append("N<S")
                elif nifty > slow_ema:
                    signs.append("N>S")
                else:
                    signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"{entry_reason} (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        return f"{entry_reason} (N:{nifty:.2f})"


def format_exit_reason(exit_reason, nifty=None, fast_ema=None, slow_ema=None, stop_loss_pct=None, target_pct=None, entry_reason=None, option_type=None):
    """Format exit reason with nifty and EMA values"""
    if exit_reason == 'EMA_EXIT':
        if nifty and fast_ema and slow_ema:
            # Show all relationships - always show F vs S, N vs F, N vs S
            signs = []
            if fast_ema > slow_ema:
                signs.append("F>S")
            elif fast_ema < slow_ema:
                signs.append("F<S")
            else:
                signs.append("F=S")
            if nifty < fast_ema:
                signs.append("N<F")
            elif nifty > fast_ema:
                signs.append("N>F")
            else:
                signs.append("N=F")
            if nifty < slow_ema:
                signs.append("N<S")
            elif nifty > slow_ema:
                signs.append("N>S")
            else:
                signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"EMA_EXIT (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        return "EMA_EXIT"
    elif exit_reason == 'STOP_LOSS':
        if stop_loss_pct:
            return f"STOP_LOSS ({stop_loss_pct}% loss)"
        return "STOP_LOSS"
    elif exit_reason == 'TARGET_HIT':
        if target_pct:
            return f"TARGET_HIT ({target_pct}% profit)"
        return "TARGET_HIT"
    elif exit_reason == 'SCHEDULED_EXIT':
        if nifty and fast_ema and slow_ema:
            # Show all relationships - always show F vs S, N vs F, N vs S
            signs = []
            if fast_ema > slow_ema:
                signs.append("F>S")
            elif fast_ema < slow_ema:
                signs.append("F<S")
            else:
                signs.append("F=S")
            if nifty > fast_ema:
                signs.append("N>F")
            elif nifty < fast_ema:
                signs.append("N<F")
            else:
                signs.append("N=F")
            if nifty > slow_ema:
                signs.append("N>S")
            elif nifty < slow_ema:
                signs.append("N<S")
            else:
                signs.append("N=S")
            sign_str = ", ".join(signs) if signs else ""
            return f"SCHEDULED_EXIT (N:{nifty:.2f}, F:{fast_ema:.2f}, S:{slow_ema:.2f}, {sign_str})"
        elif nifty:
            return f"SCHEDULED_EXIT (N:{nifty:.2f})"
        return "SCHEDULED_EXIT"
    else:
        return exit_reason or "N/A"


def prepare_trade_rows(results):
    """Prepare trade rows with cumulative P&L for display"""
    # Load config to get stop_loss_percentage and target_percentage
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        stop_loss_pct = config.get('options', {}).get('stop_loss_percentage', 30)
        target_pct = config.get('options', {}).get('target_percentage', 0)
    except:
        stop_loss_pct = 30
        target_pct = 0
    
    # Load nifty data for getting EMA values at specific entry times (for EMA_MIXED)
    nifty_data = None
    if os.path.exists(NIFTY_INTRADAY_JSON):
        try:
            with open(NIFTY_INTRADAY_JSON, 'r') as f:
                nifty_data = json.load(f)
        except:
            pass
    
    rows = []
    cumulative_sum = 0
    
    for r in results:
        entry_time_str = r['entry_time'].split(' ')[1][:5]
        entry_reason = r.get('entry_reason', 'NORMAL')
        
        # Skip trades that didn't enter due to VIX threshold or EMA neutral - show as single row
        if entry_reason in ['VIX_THRESHOLD_EXCEEDED', 'EMA_NEUTRAL']:
            formatted_entry = format_entry_reason(
                entry_reason,
                r.get('nifty_entry_price', 0),
                r.get('fast_ema_at_entry'),
                r.get('slow_ema_at_entry'),
                r.get('vix_at_entry')
            )
            rows.append({
                'date': r['date'],
                'trade_number': 1,
                'entry_time': entry_time_str,
                'exit_time': entry_time_str,  # Same as entry since no trade occurred
                'entry_reason': formatted_entry,
                'exit_reason': 'N/A',
                'stopped': False,
                'expiry_date': r.get('expiry_date'),
                'vix_at_entry': r.get('vix_at_entry'),
                'vix_at_exit': r.get('vix_at_exit'),
                'option_type': 'SKIP',
                'strike': None,
                'entry_price': None,
                'exit_price': None,
                'pnl': 0.0,
                'cumulative_pnl': cumulative_sum
            })
            continue
        
        # Get trade number (for re-entry display)
        trade_number = r.get('trade_number', 1)
        
        # CE row - use individual exit time and reason (only if CE was traded)
        ce_pnl = r.get('ce_pnl', 0)
        if r.get('ce_strike') is not None:
            # Use CE-specific entry time if available, otherwise use main entry_time
            ce_entry_time_str = r.get('ce_entry_time', r['entry_time']).split(' ')[1][:5] if r.get('ce_entry_time') else entry_time_str
            ce_exit_time_str = r.get('ce_exit_time', r['exit_time']).split(' ')[1][:5] if r.get('ce_exit_time') else entry_time_str
            ce_exit_reason = r.get('ce_exit_reason', 'SCHEDULED_EXIT')
            ce_stopped = r.get('ce_stopped', False)
            
            # Format entry and exit reasons with values
            # For EMA_MIXED, get values at CE entry time
            ce_entry_time_full = r.get('ce_entry_time', r['entry_time'])
            formatted_entry = format_entry_reason(
                entry_reason,
                r.get('nifty_entry_price', 0),
                r.get('fast_ema_at_entry'),
                r.get('slow_ema_at_entry'),
                r.get('vix_at_entry'),
                option_type='CE',
                nifty_data=nifty_data,
                date_str=r.get('date'),
                entry_time_str=ce_entry_time_full
            )
            formatted_exit = format_exit_reason(
                ce_exit_reason,
                r.get('nifty_exit_price'),
                r.get('fast_ema_at_exit'),
                r.get('slow_ema_at_exit'),
                stop_loss_pct if ce_exit_reason == 'STOP_LOSS' else None,
                target_pct if ce_exit_reason == 'TARGET_HIT' else None,
                entry_reason,
                'CE'
            )
            
            cumulative_sum += ce_pnl
            rows.append({
                'date': r['date'],
                'trade_number': trade_number,
                'entry_time': ce_entry_time_str,
                'exit_time': ce_exit_time_str,
                'entry_reason': formatted_entry,
                'exit_reason': formatted_exit,
                'stopped': ce_stopped,
                'expiry_date': r.get('expiry_date'),
                'vix_at_entry': r.get('vix_at_entry'),
                'vix_at_exit': r.get('vix_at_exit'),
                'option_type': 'CE',
                'strike': r.get('ce_strike'),
                'entry_price': r.get('ce_entry_price'),
                'exit_price': r.get('ce_exit_price'),
                'pnl': ce_pnl,
                'cumulative_pnl': cumulative_sum
            })
        
        # PE row - use individual exit time and reason (only if PE was traded)
        pe_pnl = r.get('pe_pnl', 0)
        if r.get('pe_strike') is not None:
            # Use PE-specific entry time if available, otherwise use main entry_time
            pe_entry_time_str = r.get('pe_entry_time', r['entry_time']).split(' ')[1][:5] if r.get('pe_entry_time') else entry_time_str
            pe_exit_time_str = r.get('pe_exit_time', r['exit_time']).split(' ')[1][:5] if r.get('pe_exit_time') else entry_time_str
            pe_exit_reason = r.get('pe_exit_reason', 'SCHEDULED_EXIT')
            pe_stopped = r.get('pe_stopped', False)
            
            # Format entry and exit reasons with values
            # For EMA_MIXED, get values at PE entry time
            pe_entry_time_full = r.get('pe_entry_time', r['entry_time'])
            formatted_entry = format_entry_reason(
                entry_reason,
                r.get('nifty_entry_price', 0),
                r.get('fast_ema_at_entry'),
                r.get('slow_ema_at_entry'),
                r.get('vix_at_entry'),
                option_type='PE',
                nifty_data=nifty_data,
                date_str=r.get('date'),
                entry_time_str=pe_entry_time_full
            )
            formatted_exit = format_exit_reason(
                pe_exit_reason,
                r.get('nifty_exit_price'),
                r.get('fast_ema_at_exit'),
                r.get('slow_ema_at_exit'),
                stop_loss_pct if pe_exit_reason == 'STOP_LOSS' else None,
                target_pct if pe_exit_reason == 'TARGET_HIT' else None,
                entry_reason,
                'PE'
            )
            
            cumulative_sum += pe_pnl
            rows.append({
                'date': r['date'],
                'trade_number': trade_number,
                'entry_time': pe_entry_time_str,
                'exit_time': pe_exit_time_str,
                'entry_reason': formatted_entry,
                'exit_reason': formatted_exit,
                'stopped': pe_stopped,
                'expiry_date': r.get('expiry_date'),
                'vix_at_entry': r.get('vix_at_entry'),
                'vix_at_exit': r.get('vix_at_exit'),
                'option_type': 'PE',
                'strike': r.get('pe_strike'),
                'entry_price': r.get('pe_entry_price'),
                'exit_price': r.get('pe_exit_price'),
                'pnl': pe_pnl,
                'cumulative_pnl': cumulative_sum
            })
    
    # Sort rows by date first, then by entry_time
    rows.sort(key=lambda x: (x['date'], x['entry_time']))
    
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
                        'volume': entry.get('volume', 0),
                        'fast_ema': entry.get('fast_ema'),
                        'slow_ema': entry.get('slow_ema')
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
                        'volume': entry.get('volume', 0),
                        'fast_ema': entry.get('fast_ema'),
                        'slow_ema': entry.get('slow_ema')
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


def load_vix_intraday_data(start_date, end_date):
    """Load and filter VIX intraday data for the backtest period"""
    if not os.path.exists(VIX_INTRADAY_JSON):
        return None
    
    try:
        with open(VIX_INTRADAY_JSON, 'r') as f:
            vix_data = json.load(f)
        
        # Filter data for the selected date range
        filtered_data = []
        
        # Get data for the selected date range
        for date_key in vix_data:
            if start_date <= date_key <= end_date:
                for entry in vix_data[date_key]:
                    filtered_data.append({
                        'time': entry['time'],
                        'close': entry.get('close')
                    })
        
        # Sort by time
        filtered_data.sort(key=lambda x: x['time'])
        
        return filtered_data
    except Exception as e:
        print(f"Error loading VIX data: {e}")
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
    
    # Load VIX data for the same date range
    vix_data_result = load_vix_intraday_data(start_date, end_date)
    
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
    response_data = {
        'ema_params': ema_params
    }
    
    if isinstance(nifty_data_result, dict):
        response_data['historical'] = nifty_data_result.get('historical', [])
        response_data['data'] = nifty_data_result.get('data', [])
    else:
        # Legacy format - return as data array
        response_data['historical'] = []
        response_data['data'] = nifty_data_result
    
    # Add VIX data if available
    if vix_data_result:
        response_data['vix_data'] = vix_data_result
    
    return jsonify(response_data)


@app.route('/api/config', methods=['GET'])
def get_config():
    """Load configuration from config.json"""
    try:
        config_path = 'config.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
            return jsonify(config)
        else:
            return jsonify({'error': 'Config file not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/run-backtest', methods=['POST'])
def run_backtest():
    """Save configuration and run backtest"""
    try:
        config_data = request.json
        
        # Save config to file
        config_path = 'config.json'
        with open(config_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        # Run backtest
        result = subprocess.run(
            ['python3', 'run_backtest.py'],
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Backtest completed successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Backtest failed',
                'output': result.stdout,
                'stderr': result.stderr
            }), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Backtest timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calc-ema', methods=['POST'])
def calc_ema():
    """Save EMA config and calculate EMA values to nifty_intraday_price.json"""
    try:
        # Get EMA config from request
        request_data = request.json or {}
        ema_config = request_data.get('ema_signals', {})
        
        # Load current config
        config_path = 'config.json'
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        # Update EMA signals in config
        if 'ema_signals' not in config:
            config['ema_signals'] = {}
        
        config['ema_signals'].update(ema_config)
        
        # Save updated config
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        # Run cal_ema_nifty_data.py script (it will read from the saved config.json)
        result = subprocess.run(
            ['python3', 'cal_ema_nifty_data.py'],
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'EMA values calculated and saved successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'error': 'EMA calculation failed',
                'output': result.stdout,
                'stderr': result.stderr
            }), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'EMA calculation timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3003, debug=True)

