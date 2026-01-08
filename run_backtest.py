#!/usr/bin/env python3
"""
Nifty Options Backtest Script
Backtests ATM CE and PE options strategy for specified period
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math


def load_config(config_path: str = "config.json") -> Dict:
    """Load configuration from JSON file"""
    with open(config_path, 'r') as f:
        return json.load(f)


def load_nifty_intraday(nifty_file: str) -> Dict:
    """Load Nifty intraday price data"""
    print(f"Loading Nifty intraday data from {nifty_file}...")
    with open(nifty_file, 'r') as f:
        return json.load(f)


def load_vix_intraday(vix_file: str) -> Dict:
    """Load India VIX intraday price data"""
    print(f"Loading India VIX intraday data from {vix_file}...")
    with open(vix_file, 'r') as f:
        return json.load(f)


def load_options_data(options_file: str) -> Optional[Dict]:
    """Load options data for a specific date"""
    if not os.path.exists(options_file):
        return None
    try:
        with open(options_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {options_file}: {e}")
        return None


def round_to_strike(price: float, strike_rounding: int = 50) -> int:
    """Round price to nearest strike"""
    return int(round(price / strike_rounding) * strike_rounding)


def get_price_at_time(data: List[Dict], target_time: str) -> Optional[float]:
    """Get close price at specific time from minute-level data"""
    for entry in data:
        if entry.get('datetime', entry.get('time', '')).startswith(target_time[:10] + ' ' + target_time[11:]):
            return entry.get('close')
    return None


def get_nifty_price_at_time(nifty_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get Nifty close price at specific date and time"""
    date_key = date
    if date_key not in nifty_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in nifty_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('close')
    return None


def aggregate_nifty_data_by_interval(nifty_data: Dict, date: str, interval_minutes: int) -> List[Dict]:
    """Aggregate Nifty minute-level data into specified interval candles"""
    if date not in nifty_data:
        return []
    
    minute_data = nifty_data[date]
    if not minute_data:
        return []
    
    aggregated = []
    current_bucket = None
    bucket_start_time = None
    
    for entry in minute_data:
        entry_time_str = entry.get('time')
        if not entry_time_str:
            continue
        
        try:
            entry_datetime = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
            entry_minute = entry_datetime.minute
            
            # Calculate bucket start time (round down to interval)
            bucket_minute = (entry_minute // interval_minutes) * interval_minutes
            bucket_datetime = entry_datetime.replace(minute=bucket_minute, second=0, microsecond=0)
            
            if current_bucket is None or bucket_datetime != bucket_start_time:
                # Save previous bucket if exists
                if current_bucket is not None:
                    aggregated.append(current_bucket)
                
                # Start new bucket
                bucket_start_time = bucket_datetime
                current_bucket = {
                    'time': bucket_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    'open': entry.get('open'),
                    'high': entry.get('high'),
                    'low': entry.get('low'),
                    'close': entry.get('close'),
                    'volume': entry.get('volume', 0)
                }
            else:
                # Update current bucket
                if entry.get('high') is not None:
                    current_bucket['high'] = max(current_bucket.get('high', entry.get('high')), entry.get('high'))
                if entry.get('low') is not None:
                    current_bucket['low'] = min(current_bucket.get('low', entry.get('low')), entry.get('low'))
                current_bucket['close'] = entry.get('close')  # Update close with latest
                current_bucket['volume'] = current_bucket.get('volume', 0) + entry.get('volume', 0)
        except Exception as e:
            continue
    
    # Add last bucket
    if current_bucket is not None:
        aggregated.append(current_bucket)
    
    return aggregated


def calculate_ema(prices: List[float], period: int) -> List[Optional[float]]:
    """Calculate Exponential Moving Average (EMA)"""
    if not prices or period <= 0:
        return [None] * len(prices)
    
    ema_values = []
    multiplier = 2.0 / (period + 1)
    
    # First EMA value is SMA
    if len(prices) < period:
        return [None] * len(prices)
    
    sma = sum(prices[:period]) / period
    ema_values.append(sma)
    
    # Calculate EMA for remaining values
    for i in range(period, len(prices)):
        if prices[i] is None:
            ema_values.append(None)
        else:
            ema = (prices[i] - ema_values[-1]) * multiplier + ema_values[-1]
            ema_values.append(ema)
    
    # Pad beginning with None
    return [None] * (period - 1) + ema_values


def get_ema_signal(nifty_data: Dict, date: str, time_str: str, interval_minutes: int, 
                   fast_period: int, slow_period: int) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """
    Get EMA-based trading signal at specific time.
    Calculates EMA dynamically using historical data from previous days if needed.
    Returns: (signal, fast_ema_value, slow_ema_value)
    signal: 'BULLISH', 'BEARISH', or None (NEUTRAL)
    """
    target_datetime = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M:%S")
    
    # Collect candles from current day up to target time
    aggregated = []
    if date in nifty_data:
        aggregated_all = aggregate_nifty_data_by_interval(nifty_data, date, interval_minutes)
        for candle in aggregated_all:
            candle_time = datetime.strptime(candle.get('time'), "%Y-%m-%d %H:%M:%S")
            if candle_time <= target_datetime:
                aggregated.append(candle)
            else:
                break
    
    # If we don't have enough candles, try to get from previous days
    # We need at least slow_period candles for EMA calculation
    if len(aggregated) < slow_period:
        # Get previous days' data (going backwards)
        current_date = datetime.strptime(date, "%Y-%m-%d")
        days_back = 0
        max_days_back = 10  # Look back up to 10 trading days
        
        while len(aggregated) < slow_period and days_back < max_days_back:
            days_back += 1
            prev_date = current_date - timedelta(days=days_back)
            prev_date_str = prev_date.strftime("%Y-%m-%d")
            
            # Skip weekends
            if prev_date.weekday() >= 5:
                continue
            
            if prev_date_str in nifty_data:
                prev_aggregated = aggregate_nifty_data_by_interval(nifty_data, prev_date_str, interval_minutes)
                # Prepend previous day's candles (most recent first)
                aggregated = prev_aggregated + aggregated
    
    if len(aggregated) < slow_period:
        return None, None, None
    
    # Get close prices
    closes = [candle.get('close') for candle in aggregated if candle.get('close') is not None]
    if len(closes) < slow_period:
        return None, None, None
    
    # Calculate EMAs
    fast_ema_list = calculate_ema(closes, fast_period)
    slow_ema_list = calculate_ema(closes, slow_period)
    
    if len(fast_ema_list) == 0 or len(slow_ema_list) == 0:
        return None, None, None
    
    # Get the latest EMA values (from the last candle up to target time)
    fast_ema = fast_ema_list[-1]
    slow_ema = slow_ema_list[-1]
    current_close = closes[-1]
    
    if fast_ema is None or slow_ema is None or current_close is None:
        return None, fast_ema, slow_ema
    
    # Determine signal
    # BULLISH: fast_ema > slow_ema AND close > fast_ema AND close > slow_ema
    if fast_ema > slow_ema and current_close > fast_ema and current_close > slow_ema:
        return 'BULLISH', fast_ema, slow_ema
    
    # BEARISH: fast_ema < slow_ema AND close < fast_ema AND close < slow_ema
    if fast_ema < slow_ema and current_close < fast_ema and current_close < slow_ema:
        return 'BEARISH', fast_ema, slow_ema
    
    return None, fast_ema, slow_ema  # NEUTRAL


def get_vix_price_at_time(vix_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get India VIX close price at specific date and time"""
    date_key = date
    if date_key not in vix_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in vix_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('close')
    return None


def find_atm_strike(spot_price: float, strike_rounding: int = 50) -> int:
    """Find ATM strike price"""
    return round_to_strike(spot_price, strike_rounding)


def get_option_price(options_data: Dict, option_type: str, strike: int, time_str: str) -> Optional[float]:
    """Get option price at specific time"""
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None
    
    strike_data = option_section[strike_key]
    target_datetime = f"{options_data['date']} {time_str}"
    
    for entry in strike_data:
        if entry.get('datetime') == target_datetime:
            return entry.get('close')
    
    return None


def get_option_price_closest(options_data: Dict, option_type: str, strike: int, time_str: str) -> Optional[float]:
    """Get option price closest to target time (within 5 minutes)"""
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None
    
    strike_data = option_section[strike_key]
    target_datetime = datetime.strptime(f"{options_data['date']} {time_str}", "%Y-%m-%d %H:%M:%S")
    
    closest_price = None
    min_diff = timedelta(hours=24)
    
    for entry in strike_data:
        entry_datetime_str = entry.get('datetime')
        if not entry_datetime_str:
            continue
        
        try:
            entry_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
            diff = abs(entry_datetime - target_datetime)
            
            if diff <= timedelta(minutes=5) and diff < min_diff:
                min_diff = diff
                closest_price = entry.get('close')
        except:
            continue
    
    return closest_price


def check_ema_exit(nifty_data: Dict, date: str, entry_time: str, exit_time: str,
                   entry_reason: str, interval_minutes: int, fast_period: int, slow_period: int) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """
    Check if EMA-based exit condition is met between entry and exit times.
    Calculates EMA dynamically using historical data from previous days if needed.
    For BULLISH entry (SHORT PE): exit when nifty crosses below both fast_ema and slow_ema
    For BEARISH entry (SHORT CE): exit when nifty crosses above both fast_ema and slow_ema
    Returns: (exit_time, fast_ema_value, slow_ema_value) or (None, None, None) if not triggered
    """
    if entry_reason not in ['EMA_BULLISH', 'EMA_BEARISH']:
        return None, None, None
    
    entry_datetime = datetime.strptime(f"{date} {entry_time}", "%Y-%m-%d %H:%M:%S")
    exit_datetime = datetime.strptime(f"{date} {exit_time}", "%Y-%m-%d %H:%M:%S")
    
    # Check minute-by-minute between entry and exit
    # Start checking 1 minute after entry to avoid immediate exit
    current_time = entry_datetime + timedelta(minutes=1)
    
    # Track previous state to detect crossing
    prev_nifty_price = None
    prev_fast_ema = None
    prev_slow_ema = None
    
    while current_time <= exit_datetime:
        time_str = current_time.strftime("%H:%M:%S")
        
        # Calculate EMA values dynamically
        _, fast_ema, slow_ema = get_ema_signal(nifty_data, date, time_str, interval_minutes, fast_period, slow_period)
        
        if fast_ema is None or slow_ema is None:
            current_time += timedelta(minutes=1)
            continue
        
        # Get Nifty close price at this time
        nifty_price = get_nifty_price_at_time(nifty_data, date, time_str)
        if nifty_price is None:
            current_time += timedelta(minutes=1)
            continue
        
        # Check exit conditions based on entry reason
        if entry_reason == 'EMA_BULLISH':
            # BULLISH: Exit when nifty crosses below both fast_ema and slow_ema
            # Current price must be below both EMAs
            if nifty_price < fast_ema and nifty_price < slow_ema:
                # Check if we crossed from above (previous price was above at least one EMA)
                if prev_nifty_price is not None and prev_fast_ema is not None and prev_slow_ema is not None:
                    # Crossed below: previous price was above at least one EMA, now below both
                    if prev_nifty_price >= prev_fast_ema or prev_nifty_price >= prev_slow_ema:
                        return time_str, fast_ema, slow_ema
                else:
                    # First check after entry - if already below both EMAs, exit immediately
                    # This handles case where entry condition changed immediately after entry
                    return time_str, fast_ema, slow_ema
        elif entry_reason == 'EMA_BEARISH':
            # BEARISH: Exit when nifty crosses above both fast_ema and slow_ema
            # Current price must be above both EMAs
            if nifty_price > fast_ema and nifty_price > slow_ema:
                # Check if we crossed from below (previous price was below at least one EMA)
                if prev_nifty_price is not None and prev_fast_ema is not None and prev_slow_ema is not None:
                    # Crossed above: previous price was below at least one EMA, now above both
                    if prev_nifty_price <= prev_fast_ema or prev_nifty_price <= prev_slow_ema:
                        return time_str, fast_ema, slow_ema
                else:
                    # First check after entry - if already above both EMAs, exit immediately
                    # This handles case where entry condition changed immediately after entry
                    return time_str, fast_ema, slow_ema
        
        # Update previous values for next iteration
        prev_nifty_price = nifty_price
        prev_fast_ema = fast_ema
        prev_slow_ema = slow_ema
        
        current_time += timedelta(minutes=1)
    
    return None, None, None


def check_stop_loss(options_data: Dict, option_type: str, strike: int, entry_time: str, 
                    exit_time: str, entry_price: float, stop_loss_percentage: float) -> Tuple[Optional[float], Optional[str]]:
    """
    Check if stop loss is hit between entry and exit times.
    For SHORT positions: stop loss triggers when price increases by stop_loss_percentage.
    Returns: (stop_loss_exit_price, stop_loss_exit_time) or (None, None) if not hit
    """
    if stop_loss_percentage <= 0 or entry_price is None:
        return None, None
    
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None, None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None, None
    
    strike_data = option_section[strike_key]
    entry_datetime = datetime.strptime(f"{options_data['date']} {entry_time}", "%Y-%m-%d %H:%M:%S")
    exit_datetime = datetime.strptime(f"{options_data['date']} {exit_time}", "%Y-%m-%d %H:%M:%S")
    
    # Calculate stop loss price (for SHORT: price goes UP by stop_loss_percentage)
    stop_loss_price = entry_price * (1 + stop_loss_percentage / 100)
    
    # Check prices between entry and exit times
    for entry in strike_data:
        entry_datetime_str = entry.get('datetime')
        if not entry_datetime_str:
            continue
        
        try:
            price_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
            price = entry.get('close')
            
            # Only check times between entry and exit
            if entry_datetime <= price_datetime <= exit_datetime:
                # For SHORT: stop loss triggers when price >= stop_loss_price
                if price is not None and price >= stop_loss_price:
                    return price, entry_datetime_str.split(' ')[1]  # Return time part only
        except:
            continue
    
    return None, None


def run_backtest(config: Dict) -> List[Dict]:
    """Run backtest for specified period"""
    results = []
    
    # Load data
    nifty_data = load_nifty_intraday(config['data_paths']['nifty_intraday'])
    
    # Load VIX data if path is configured
    vix_data = None
    vix_threshold = config['options'].get('vix_threshold', None)
    if vix_threshold is not None and 'vix_intraday' in config['data_paths']:
        vix_data = load_vix_intraday(config['data_paths']['vix_intraday'])
    
    # Parse dates
    start_date = datetime.strptime(config['backtest_period']['start_date'], "%Y-%m-%d")
    end_date = datetime.strptime(config['backtest_period']['end_date'], "%Y-%m-%d")
    
    entry_time = config['trading_times']['entry_time']
    exit_time = config['trading_times']['exit_time']
    
    strike_rounding = config['strike_selection']['strike_rounding']
    ce_offset = config['strike_selection']['ce_strike_offset']
    pe_offset = config['strike_selection']['pe_strike_offset']
    lot_size = config['options']['lot_size']
    lot_multiple = config['options'].get('lot_multiple', 1)
    use_next_expiry = config['options']['use_next_expiry']
    stop_loss_percentage = config['options'].get('stop_loss_percentage', 0)
    
    # EMA signal configuration
    ema_enabled = config.get('ema_signals', {}).get('enabled', False)
    ema_interval = config.get('ema_signals', {}).get('time_interval', 15)
    ema_fast = config.get('ema_signals', {}).get('fast_ema', 9)
    ema_slow = config.get('ema_signals', {}).get('slow_ema', 21)
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Skip weekends (Saturday=5, Sunday=6)
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        print(f"Processing {date_str}...")
        
        # Determine options file
        year = current_date.year
        options_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}.json"
        if use_next_expiry and os.path.exists(f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}_next_expiry.json"):
            options_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}_next_expiry.json"
        
        options_data = load_options_data(options_file)
        if not options_data:
            print(f"  No options data found for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Get Nifty prices
        nifty_entry_price = get_nifty_price_at_time(nifty_data, date_str, entry_time)
        nifty_exit_price = get_nifty_price_at_time(nifty_data, date_str, exit_time)
        
        if not nifty_entry_price or not nifty_exit_price:
            print(f"  Missing Nifty price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Check VIX threshold if configured
        entry_reason = "NORMAL"
        if vix_data is not None and vix_threshold is not None:
            vix_entry_price = get_vix_price_at_time(vix_data, date_str, entry_time)
            if vix_entry_price is not None and vix_entry_price > vix_threshold:
                print(f"  VIX threshold exceeded: {vix_entry_price} > {vix_threshold}, skipping trade")
                entry_reason = "VIX_THRESHOLD_EXCEEDED"
                # Get expiry_date from options_data
                expiry_date = options_data.get('expiry_date', None)
                # Store skipped trade result
                result = {
                    "date": date_str,
                    "entry_time": f"{date_str} {entry_time}",
                    "exit_time": f"{date_str} {entry_time}",
                    "entry_reason": entry_reason,
                    "fast_ema_at_entry": None,
                    "slow_ema_at_entry": None,
                    "expiry_date": expiry_date,
                    "vix_at_entry": round(vix_entry_price, 2),
                    "vix_at_exit": round(vix_entry_price, 2),  # Same as entry since no trade occurred
                    "nifty_entry_price": round(nifty_entry_price, 2),
                    "nifty_exit_price": round(nifty_entry_price, 2),
                    "ce_strike": None,
                    "ce_entry_price": None,
                    "ce_exit_price": None,
                    "ce_exit_time": None,
                    "ce_exit_reason": None,
                    "ce_stopped": False,
                    "ce_pnl": 0.0,
                    "pe_strike": None,
                    "pe_entry_price": None,
                    "pe_exit_price": None,
                    "pe_exit_time": None,
                    "pe_exit_reason": None,
                    "pe_stopped": False,
                    "pe_pnl": 0.0,
                    "total_pnl": 0.0
                }
                results.append(result)
                current_date += timedelta(days=1)
                continue
        
        # Check EMA signal if enabled
        ema_signal = None
        fast_ema_value = None
        slow_ema_value = None
        trade_ce = True
        trade_pe = True
        if ema_enabled:
            ema_signal, fast_ema_value, slow_ema_value = get_ema_signal(nifty_data, date_str, entry_time, ema_interval, ema_fast, ema_slow)
            if fast_ema_value is None or slow_ema_value is None:
                # EMA values are None in JSON file - this happens when there isn't enough historical data
                # to calculate EMA (e.g., slow_ema needs 63 candles, fast_ema needs 27 candles)
                trade_ce = False
                trade_pe = False
                entry_reason = "EMA_NEUTRAL"
                fast_str = f"{fast_ema_value:.2f}" if fast_ema_value is not None else "None"
                slow_str = f"{slow_ema_value:.2f}" if slow_ema_value is not None else "None"
                print(f"  EMA Signal: NEUTRAL (insufficient data) - fast_ema={fast_str}, slow_ema={slow_str} at {entry_time}")
            elif ema_signal == 'BULLISH':
                # BULLISH: Only SHORT PE
                trade_ce = False
                trade_pe = True
                entry_reason = "EMA_BULLISH"
                print(f"  EMA Signal: BULLISH - Fast EMA: {fast_ema_value:.2f}, Slow EMA: {slow_ema_value:.2f} - Entering PE only")
            elif ema_signal == 'BEARISH':
                # BEARISH: Only SHORT CE
                trade_ce = True
                trade_pe = False
                entry_reason = "EMA_BEARISH"
                print(f"  EMA Signal: BEARISH - Fast EMA: {fast_ema_value:.2f}, Slow EMA: {slow_ema_value:.2f} - Entering CE only")
            else:
                # NEUTRAL: Skip trade (has EMA values but signal is neutral)
                trade_ce = False
                trade_pe = False
                entry_reason = "EMA_NEUTRAL"
                print(f"  EMA Signal: NEUTRAL - Fast EMA: {fast_ema_value:.2f}, Slow EMA: {slow_ema_value:.2f} - Skipping trade")
                # Store skipped trade result
                expiry_date = options_data.get('expiry_date', None)
                vix_entry_price = get_vix_price_at_time(vix_data, date_str, entry_time) if vix_data else None
                result = {
                    "date": date_str,
                    "entry_time": f"{date_str} {entry_time}",
                    "exit_time": f"{date_str} {entry_time}",
                    "entry_reason": entry_reason,
                    "fast_ema_at_entry": round(fast_ema_value, 2) if fast_ema_value is not None else None,
                    "slow_ema_at_entry": round(slow_ema_value, 2) if slow_ema_value is not None else None,
                    "expiry_date": expiry_date,
                    "vix_at_entry": round(vix_entry_price, 2) if vix_entry_price else None,
                    "vix_at_exit": round(vix_entry_price, 2) if vix_entry_price else None,
                    "nifty_entry_price": round(nifty_entry_price, 2),
                    "nifty_exit_price": round(nifty_entry_price, 2),
                    "ce_strike": None,
                    "ce_entry_price": None,
                    "ce_exit_price": None,
                    "ce_exit_time": None,
                    "ce_exit_reason": None,
                    "ce_stopped": False,
                    "ce_pnl": 0.0,
                    "pe_strike": None,
                    "pe_entry_price": None,
                    "pe_exit_price": None,
                    "pe_exit_time": None,
                    "pe_exit_reason": None,
                    "pe_stopped": False,
                    "pe_pnl": 0.0,
                    "total_pnl": 0.0
                }
                results.append(result)
                current_date += timedelta(days=1)
                continue
        
        # Calculate strikes
        atm_strike = find_atm_strike(nifty_entry_price, strike_rounding)
        ce_strike = atm_strike + (ce_offset * strike_rounding)
        pe_strike = atm_strike + (pe_offset * strike_rounding)
        
        # Get option entry prices (only for legs we're trading)
        ce_entry_price = None
        pe_entry_price = None
        
        if trade_ce:
            ce_entry_price = get_option_price_closest(options_data, 'CE', ce_strike, entry_time)
        if trade_pe:
            pe_entry_price = get_option_price_closest(options_data, 'PE', pe_strike, entry_time)
        
        # Check if we have at least one valid entry price
        if (trade_ce and ce_entry_price is None) or (trade_pe and pe_entry_price is None):
            print(f"  Missing option entry price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Check for EMA exit first (if EMA-based entry)
        # EMA exit applies to the entire trade (both legs exit together)
        ema_exit_time = None
        ema_exit_fast_ema = None
        ema_exit_slow_ema = None
        if ema_enabled and entry_reason in ['EMA_BULLISH', 'EMA_BEARISH']:
            ema_exit_time, ema_exit_fast_ema, ema_exit_slow_ema = check_ema_exit(
                nifty_data, date_str, entry_time, exit_time, entry_reason,
                ema_interval, ema_fast, ema_slow
            )
            if ema_exit_time is not None:
                print(f"  EMA Exit triggered at {ema_exit_time} - Fast EMA: {ema_exit_fast_ema:.2f}, Slow EMA: {ema_exit_slow_ema:.2f}")
        
        # Check for stop loss - each leg runs independently
        # CE leg: Check stop loss only if we're trading CE
        ce_exit_price = None
        ce_exit_time = None
        ce_stopped = False
        ce_exit_reason = None
        
        if trade_ce:
            # Priority: EMA exit > Stop loss > Scheduled exit
            if ema_exit_time is not None:
                # EMA exit triggered - exit CE at EMA exit time
                ce_exit_price = get_option_price_closest(options_data, 'CE', ce_strike, ema_exit_time)
                ce_exit_time = ema_exit_time
                ce_stopped = False
                ce_exit_reason = "EMA_EXIT"
            else:
                # Check stop loss
                ce_stop_loss_price, ce_stop_loss_time = check_stop_loss(
                    options_data, 'CE', ce_strike, entry_time, exit_time, 
                    ce_entry_price, stop_loss_percentage
                )
                
                # Determine CE exit price and time
                if ce_stop_loss_price is not None:
                    ce_exit_price = ce_stop_loss_price
                    ce_exit_time = ce_stop_loss_time
                    ce_stopped = True
                    ce_exit_reason = "STOP_LOSS"
                else:
                    # CE did not hit stop loss, use scheduled exit
                    ce_exit_price = get_option_price_closest(options_data, 'CE', ce_strike, exit_time)
                    ce_exit_time = exit_time
                    ce_stopped = False
                    ce_exit_reason = "SCHEDULED_EXIT"
        
        # PE leg: Check stop loss only if we're trading PE
        pe_exit_price = None
        pe_exit_time = None
        pe_stopped = False
        pe_exit_reason = None
        
        if trade_pe:
            # Priority: EMA exit > Stop loss > Scheduled exit
            if ema_exit_time is not None:
                # EMA exit triggered - exit PE at EMA exit time
                pe_exit_price = get_option_price_closest(options_data, 'PE', pe_strike, ema_exit_time)
                pe_exit_time = ema_exit_time
                pe_stopped = False
                pe_exit_reason = "EMA_EXIT"
            else:
                # Check stop loss
                pe_stop_loss_price, pe_stop_loss_time = check_stop_loss(
                    options_data, 'PE', pe_strike, entry_time, exit_time,
                    pe_entry_price, stop_loss_percentage
                )
                
                # Determine PE exit price and time
                if pe_stop_loss_price is not None:
                    pe_exit_price = pe_stop_loss_price
                    pe_exit_time = pe_stop_loss_time
                    pe_stopped = True
                    pe_exit_reason = "STOP_LOSS"
                else:
                    # PE did not hit stop loss, use scheduled exit
                    pe_exit_price = get_option_price_closest(options_data, 'PE', pe_strike, exit_time)
                    pe_exit_time = exit_time
                    pe_stopped = False
                    pe_exit_reason = "SCHEDULED_EXIT"
        
        # Check if we have valid exit prices for legs we're trading
        if (trade_ce and ce_exit_price is None) or (trade_pe and pe_exit_price is None):
            print(f"  Missing option exit price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Calculate P&L (SHORT positions: sell at entry, buy back at exit)
        # Apply lot_multiple to scale the position size
        ce_pnl = 0.0
        pe_pnl = 0.0
        
        if trade_ce and ce_entry_price is not None and ce_exit_price is not None:
            ce_pnl = (ce_entry_price - ce_exit_price) * lot_size * lot_multiple
        
        if trade_pe and pe_entry_price is not None and pe_exit_price is not None:
            pe_pnl = (pe_entry_price - pe_exit_price) * lot_size * lot_multiple
        
        total_pnl = ce_pnl + pe_pnl
        
        # Determine overall exit time (earliest of CE/PE exit times for display purposes)
        # Note: Each leg exits independently, but we track the earliest for overall exit time
        exit_times = []
        if ce_exit_time:
            exit_times.append(ce_exit_time)
        if pe_exit_time:
            exit_times.append(pe_exit_time)
        overall_exit_time = min(exit_times) if exit_times else exit_time
        
        # Get Nifty price at overall exit time (earliest exit)
        nifty_exit_price = get_nifty_price_at_time(nifty_data, date_str, overall_exit_time)
        if nifty_exit_price is None:
            # Fallback to scheduled exit time price if not available
            nifty_exit_price = get_nifty_price_at_time(nifty_data, date_str, exit_time)
        
        # Get VIX at entry and exit for record keeping
        vix_at_entry = None
        vix_at_exit = None
        if vix_data is not None:
            vix_at_entry = get_vix_price_at_time(vix_data, date_str, entry_time)
            vix_at_exit = get_vix_price_at_time(vix_data, date_str, overall_exit_time)
        
        # Get expiry_date from options_data
        expiry_date = options_data.get('expiry_date', None)
        
        # Store result
        result = {
            "date": date_str,
            "entry_time": f"{date_str} {entry_time}",
            "exit_time": f"{date_str} {overall_exit_time}",
            "entry_reason": entry_reason,
            "fast_ema_at_entry": round(fast_ema_value, 2) if fast_ema_value is not None else None,
            "slow_ema_at_entry": round(slow_ema_value, 2) if slow_ema_value is not None else None,
            "expiry_date": expiry_date,
            "vix_at_entry": round(vix_at_entry, 2) if vix_at_entry is not None else None,
            "vix_at_exit": round(vix_at_exit, 2) if vix_at_exit is not None else None,
            "nifty_entry_price": round(nifty_entry_price, 2),
            "nifty_exit_price": round(nifty_exit_price, 2) if nifty_exit_price else round(get_nifty_price_at_time(nifty_data, date_str, exit_time) or 0, 2),
            "ce_strike": ce_strike if trade_ce else None,
            "ce_entry_price": round(ce_entry_price, 2) if ce_entry_price else None,
            "ce_exit_price": round(ce_exit_price, 2) if ce_exit_price else None,
            "ce_exit_time": f"{date_str} {ce_exit_time}" if ce_exit_time else None,
            "ce_exit_reason": ce_exit_reason,
            "ce_stopped": ce_stopped,
            "ce_pnl": round(ce_pnl, 2),
            "pe_strike": pe_strike if trade_pe else None,
            "pe_entry_price": round(pe_entry_price, 2) if pe_entry_price else None,
            "pe_exit_price": round(pe_exit_price, 2) if pe_exit_price else None,
            "pe_exit_time": f"{date_str} {pe_exit_time}" if pe_exit_time else None,
            "pe_exit_reason": pe_exit_reason,
            "pe_stopped": pe_stopped,
            "pe_pnl": round(pe_pnl, 2),
            "total_pnl": round(total_pnl, 2)
        }
        
        results.append(result)
        print(f"  CE Strike: {ce_strike}, Entry: {ce_entry_price}, Exit: {ce_exit_price} at {ce_exit_time} ({ce_exit_reason}), P&L: {ce_pnl}")
        print(f"  PE Strike: {pe_strike}, Entry: {pe_entry_price}, Exit: {pe_exit_price} at {pe_exit_time} ({pe_exit_reason}), P&L: {pe_pnl}")
        print(f"  Total P&L: {total_pnl}")
        if ce_exit_reason == "STOP_LOSS" and pe_exit_reason == "STOP_LOSS":
            print(f"    → Both legs hit stop loss")
        elif ce_exit_reason == "STOP_LOSS":
            print(f"    → CE hit stop loss at {ce_exit_time}, PE continued until {pe_exit_time}")
        elif pe_exit_reason == "STOP_LOSS":
            print(f"    → PE hit stop loss at {pe_exit_time}, CE continued until {ce_exit_time}")
        
        current_date += timedelta(days=1)
    
    return results


def calculate_drawdown_metrics(results: List[Dict]) -> tuple:
    """Calculate max drawdown and max drawdown days from results"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED) for drawdown calculation
    actual_trades = [r for r in results if r.get('entry_reason') != 'VIX_THRESHOLD_EXCEEDED']
    
    if not actual_trades:
        return 0.0, 0
    
    # Calculate cumulative P&L for each trade day
    cumulative_pnl = []
    cumsum = 0
    for r in actual_trades:
        cumsum += r['ce_pnl'] + r['pe_pnl']
        cumulative_pnl.append(cumsum)
    
    if not cumulative_pnl:
        return 0.0, 0
    
    # Calculate max drawdown
    max_drawdown = 0.0
    peak = cumulative_pnl[0]
    max_drawdown_days = 0
    current_drawdown_days = 0
    
    for i, cum_pnl in enumerate(cumulative_pnl):
        # Update peak
        if cum_pnl > peak:
            peak = cum_pnl
            current_drawdown_days = 0
        else:
            # Calculate drawdown from peak
            drawdown = peak - cum_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            
            # Count drawdown days (days below peak)
            if cum_pnl < peak:
                current_drawdown_days += 1
                if current_drawdown_days > max_drawdown_days:
                    max_drawdown_days = current_drawdown_days
    
    return round(max_drawdown, 2), max_drawdown_days


def save_results(results: List[Dict], output_file: str, per_order_charges: float = 30.0, lot_multiple: int = 1):
    """Save backtest results to JSON file"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED) for trade statistics
    actual_trades = [r for r in results if r.get('entry_reason') != 'VIX_THRESHOLD_EXCEEDED']
    
    max_drawdown, max_drawdown_days = calculate_drawdown_metrics(results)
    
    # Calculate total charges: Each actual trade day has 4 orders (CE entry, CE exit, PE entry, PE exit)
    # Note: lot_multiple affects position size (P&L) but not number of orders
    # Each order can be for multiple lots, so it's still 1 order per leg per action
    total_orders = len(actual_trades) * 4
    total_charges = total_orders * per_order_charges
    
    # Calculate net P&L after charges (only for actual trades)
    total_pnl = round(sum(r['total_pnl'] for r in actual_trades), 2)
    net_pnl = round(total_pnl - total_charges, 2)
    
    # Total trading days includes all days (skipped + actual trades)
    total_trading_days = len(results)
    
    summary = {
        "total_trading_days": total_trading_days,
        "total_trades": len(actual_trades),
        "total_pnl": total_pnl,
        "total_orders": total_orders,
        "per_order_charges": per_order_charges,
        "total_charges": round(total_charges, 2),
        "net_pnl": net_pnl,
        "winning_trades": len([r for r in actual_trades if r['total_pnl'] > 0]),
        "losing_trades": len([r for r in actual_trades if r['total_pnl'] < 0]),
        "average_pnl": round(sum(r['total_pnl'] for r in actual_trades) / len(actual_trades) if actual_trades else 0, 2),
        "max_profit": round(max([r['total_pnl'] for r in actual_trades]) if actual_trades else 0, 2),
        "max_loss": round(min([r['total_pnl'] for r in actual_trades]) if actual_trades else 0, 2),
        "max_drawdown": max_drawdown,
        "max_drawdown_days": max_drawdown_days,
        "results": results
    }
    
    with open(output_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nResults saved to {output_file}")
    print(f"Total Trading Days: {summary['total_trading_days']}")
    print(f"Total Trades: {summary['total_trades']}")
    print(f"Total Orders: {summary['total_orders']}")
    print(f"Per Order Charges: ₹{summary['per_order_charges']}")
    print(f"Total Charges: ₹{summary['total_charges']}")
    print(f"Total P&L: ₹{summary['total_pnl']}")
    print(f"Net P&L (after charges): ₹{summary['net_pnl']}")
    print(f"Winning Trades: {summary['winning_trades']}")
    print(f"Losing Trades: {summary['losing_trades']}")
    print(f"Average P&L: ₹{summary['average_pnl']}")
    print(f"Max Drawdown: ₹{summary['max_drawdown']}")
    print(f"Max Drawdown Days: {summary['max_drawdown_days']}")


def main():
    """Main function"""
    print("=" * 60)
    print("Nifty Options Backtest")
    print("=" * 60)
    
    # Load configuration
    config = load_config()
    
    # Run backtest
    results = run_backtest(config)
    
    if not results:
        print("No results generated. Please check your data files.")
        return
    
    # Save results
    output_json = config['output']['results_json']
    per_order_charges = config['options'].get('per_order_charges', 30.0)
    lot_multiple = config['options'].get('lot_multiple', 1)
    save_results(results, output_json, per_order_charges, lot_multiple)
    
    print("\nBacktest completed successfully!")
    print(f"View results in web app: python3 app.py")


if __name__ == "__main__":
    main()

