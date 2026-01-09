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


def get_ema_from_nifty_data(nifty_data: Dict, date: str, time_str: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Get pre-calculated fast_ema and slow_ema values from nifty_intraday_price.json
    Returns: (fast_ema, slow_ema)
    """
    date_key = date
    if date_key not in nifty_data:
        return None, None
    
    target_time = f"{date} {time_str}"
    for entry in nifty_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('fast_ema'), entry.get('slow_ema')
    return None, None


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
    Legacy helper: get EMA-based trading signal at specific time.
    Kept for backwards compatibility (used for formatting / metrics),
    but main entry logic for EMA signals is handled separately.
    """
    # Get pre-calculated EMA values from nifty data
    fast_ema, slow_ema = get_ema_from_nifty_data(nifty_data, date, time_str)
    
    if fast_ema is None or slow_ema is None:
        return None, fast_ema, slow_ema
    
    # Get current close price
    current_close = get_nifty_price_at_time(nifty_data, date, time_str)
    
    if current_close is None:
        return None, fast_ema, slow_ema
    
    # Determine signal
    if fast_ema > slow_ema and current_close > fast_ema and current_close > slow_ema:
        return 'BULLISH', fast_ema, slow_ema
    if fast_ema < slow_ema and current_close < fast_ema and current_close < slow_ema:
        return 'BEARISH', fast_ema, slow_ema
    
    return None, fast_ema, slow_ema  # NEUTRAL


def find_ema_entry_times(
    nifty_data: Dict,
    date: str,
    entry_time: str,
    exit_time: str,
    interval_minutes: int
) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
    """
    Find first EMA-based entry times for CE and PE independently between entry_time and exit_time.
    
    - CE entry (BEARISH): F < S, N < F, N < S  -> SHORT CE
    - PE entry (BULLISH): F > S, N > F, N > S  -> SHORT PE
    
    Returns:
        (ce_entry_time_str, pe_entry_time_str, first_fast_ema, first_slow_ema)
    where times are in '%H:%M:%S' format.
    """
    ce_entry_time: Optional[str] = None
    pe_entry_time: Optional[str] = None
    first_fast_ema: Optional[float] = None
    first_slow_ema: Optional[float] = None
    
    entry_dt = datetime.strptime(f"{date} {entry_time}", "%Y-%m-%d %H:%M:%S")
    exit_dt = datetime.strptime(f"{date} {exit_time}", "%Y-%m-%d %H:%M:%S")
    current_dt = entry_dt
    
    while current_dt <= exit_dt and (ce_entry_time is None or pe_entry_time is None):
        time_str = current_dt.strftime("%H:%M:%S")
        
        fast_ema, slow_ema = get_ema_from_nifty_data(nifty_data, date, time_str)
        if fast_ema is None or slow_ema is None:
            current_dt += timedelta(minutes=interval_minutes)
            continue
        
        price = get_nifty_price_at_time(nifty_data, date, time_str)
        if price is None:
            current_dt += timedelta(minutes=interval_minutes)
            continue
        
        # BEARISH: F<S, N<F, N<S -> SHORT CE
        if ce_entry_time is None and fast_ema < slow_ema and price < fast_ema and price < slow_ema:
            ce_entry_time = time_str
            if first_fast_ema is None:
                first_fast_ema = fast_ema
                first_slow_ema = slow_ema
        
        # BULLISH: F>S, N>F, N>S -> SHORT PE
        if pe_entry_time is None and fast_ema > slow_ema and price > fast_ema and price > slow_ema:
            pe_entry_time = time_str
            if first_fast_ema is None:
                first_fast_ema = fast_ema
                first_slow_ema = slow_ema
        
        current_dt += timedelta(minutes=interval_minutes)
    
    return ce_entry_time, pe_entry_time, first_fast_ema, first_slow_ema


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
    Uses pre-calculated EMA values from nifty_intraday_price.json.
    For BULLISH entry (SHORT PE): exit when nifty crosses below EITHER fast_ema OR slow_ema
    For BEARISH entry (SHORT CE): exit when nifty crosses above EITHER fast_ema OR slow_ema
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
        
        # Get pre-calculated EMA values from nifty data
        fast_ema, slow_ema = get_ema_from_nifty_data(nifty_data, date, time_str)
        
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
            # BULLISH: Exit when nifty crosses below EITHER fast_ema OR slow_ema
            # Current price must be below at least one EMA
            if nifty_price < fast_ema or nifty_price < slow_ema:
                # Check if we crossed from above (previous price was above both EMAs)
                if prev_nifty_price is not None and prev_fast_ema is not None and prev_slow_ema is not None:
                    # Crossed below: previous price was above both EMAs, now below at least one
                    if prev_nifty_price >= prev_fast_ema and prev_nifty_price >= prev_slow_ema:
                        return time_str, fast_ema, slow_ema
                # Don't exit on first check - need to see a crossing from above
        elif entry_reason == 'EMA_BEARISH':
            # BEARISH: Exit when nifty crosses above EITHER fast_ema OR slow_ema
            # Current price must be above at least one EMA
            if nifty_price > fast_ema or nifty_price > slow_ema:
                # Check if we crossed from below (previous price was below both EMAs)
                if prev_nifty_price is not None and prev_fast_ema is not None and prev_slow_ema is not None:
                    # Crossed above: previous price was below both EMAs, now above at least one
                    if prev_nifty_price <= prev_fast_ema and prev_nifty_price <= prev_slow_ema:
                        return time_str, fast_ema, slow_ema
                # Don't exit on first check - need to see a crossing from below
        
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


def is_reentry_allowed(reentry_time: str, no_reentry_after: str) -> bool:
    """
    Check if re-entry is allowed based on time cutoff.
    Returns True if re-entry is allowed, False if past the cutoff time.
    """
    if no_reentry_after is None:
        return True
    
    try:
        # Parse times (just the time portion)
        reentry_t = datetime.strptime(reentry_time, "%H:%M:%S").time()
        cutoff_t = datetime.strptime(no_reentry_after, "%H:%M:%S").time()
        return reentry_t < cutoff_t
    except:
        return True  # Allow re-entry if time parsing fails


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
    use_ema_exit = config.get('ema_signals', {}).get('use_ema_exit', True)
    ema_interval = config.get('ema_signals', {}).get('time_interval', 15)
    ema_fast = config.get('ema_signals', {}).get('fast_ema', 9)
    ema_slow = config.get('ema_signals', {}).get('slow_ema', 21)
    
    # Re-entry configuration
    reentry_enabled = config.get('reentry', {}).get('enabled', False)
    max_reentries = config.get('reentry', {}).get('max_reentries', 0)
    no_reentry_after = config.get('reentry', {}).get('no_reentry_after', None)  # Time after which no re-entry allowed
    
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
        
        # Determine EMA-based entries for each leg, if enabled
        trade_ce = False
        trade_pe = False
        fast_ema_value = None
        slow_ema_value = None
        ce_entry_time = entry_time
        pe_entry_time = entry_time
        
        if ema_enabled:
            ce_entry_time, pe_entry_time, fast_ema_value, slow_ema_value = find_ema_entry_times(
                nifty_data, date_str, entry_time, exit_time, ema_interval
            )
            
            trade_ce = ce_entry_time is not None
            trade_pe = pe_entry_time is not None
            
            # Case 1: No clear EMA signal for either leg -> skip as EMA_NEUTRAL
            if not trade_ce and not trade_pe:
                entry_reason = "EMA_NEUTRAL"
                fast_str = f"{fast_ema_value:.2f}" if fast_ema_value is not None else "None"
                slow_str = f"{slow_ema_value:.2f}" if slow_ema_value is not None else "None"
                print(f"  EMA Signal: NEUTRAL - Fast EMA: {fast_str}, Slow EMA: {slow_str} - Skipping trade")
                
                expiry_date = options_data.get('expiry_date', None)
                vix_entry_price = get_vix_price_at_time(vix_data, date_str, entry_time) if vix_data else None
                result = {
                    "date": date_str,
                    "trade_number": 1,
                    "entry_time": f"{date_str} {entry_time}",
                    "exit_time": f"{date_str} {entry_time}",
                    "entry_reason": entry_reason,
                    "fast_ema_at_entry": round(fast_ema_value, 2) if fast_ema_value is not None else None,
                    "slow_ema_at_entry": round(slow_ema_value, 2) if slow_ema_value is not None else None,
                    "fast_ema_at_exit": None,
                    "slow_ema_at_exit": None,
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
            
            # Case 2: One or both sides have valid signals -> trade all valid legs
            if trade_ce and trade_pe:
                entry_reason = "EMA_MIXED"
                print(f"  EMA Signals: CE (BEARISH) at {ce_entry_time}, PE (BULLISH) at {pe_entry_time} - entering both legs")
            elif trade_ce and not trade_pe:
                # CE comes from BEARISH EMA conditions
                entry_reason = "EMA_BEARISH"
                print(f"  EMA Signal: BEARISH - Short CE only (first entry at {ce_entry_time})")
            elif trade_pe and not trade_ce:
                # PE comes from BULLISH EMA conditions
                entry_reason = "EMA_BULLISH"
                print(f"  EMA Signal: BULLISH - Short PE only (first entry at {pe_entry_time})")
        else:
            # Non-EMA mode: trade both legs from configured entry_time
            trade_ce = True
            trade_pe = True
            ce_entry_time = entry_time
            pe_entry_time = entry_time
            entry_reason = "NORMAL"
        
        # Calculate strikes and option entry prices independently for each leg
        ce_strike: Optional[int] = None
        pe_strike: Optional[int] = None
        ce_entry_price: Optional[float] = None
        pe_entry_price: Optional[float] = None
        
        if trade_ce:
            ce_nifty_entry = get_nifty_price_at_time(nifty_data, date_str, ce_entry_time) or nifty_entry_price
            ce_strike = find_atm_strike(ce_nifty_entry, strike_rounding) + (ce_offset * strike_rounding)
            ce_entry_price = get_option_price_closest(options_data, 'CE', ce_strike, ce_entry_time)
        
        if trade_pe:
            pe_nifty_entry = get_nifty_price_at_time(nifty_data, date_str, pe_entry_time) or nifty_entry_price
            pe_strike = find_atm_strike(pe_nifty_entry, strike_rounding) + (pe_offset * strike_rounding)
            pe_entry_price = get_option_price_closest(options_data, 'PE', pe_strike, pe_entry_time)
        
        # Check if we have valid entry prices for all active legs
        if (trade_ce and ce_entry_price is None) or (trade_pe and pe_entry_price is None):
            print(f"  Missing option entry price data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Get expiry_date from options_data
        expiry_date = options_data.get('expiry_date', None)
        
        # Get VIX at entry for record keeping (still using configured entry_time)
        vix_at_entry = None
        if vix_data is not None:
            vix_at_entry = get_vix_price_at_time(vix_data, date_str, entry_time)
        
        # EMA values at exit
        fast_ema_exit = None
        slow_ema_exit = None
        if ema_enabled:
            fast_ema_exit, slow_ema_exit = get_ema_from_nifty_data(nifty_data, date_str, exit_time)
        
        # Calculate exit prices (always at configured exit_time for EMA strategy)
        ce_exit_price: Optional[float] = None
        pe_exit_price: Optional[float] = None
        
        if trade_ce and ce_strike is not None:
            ce_exit_price = get_option_price_closest(options_data, 'CE', ce_strike, exit_time)
        if trade_pe and pe_strike is not None:
            pe_exit_price = get_option_price_closest(options_data, 'PE', pe_strike, exit_time)
        
        # Calculate P&L for each leg
        ce_pnl = 0.0
        pe_pnl = 0.0
        if trade_ce and ce_entry_price is not None and ce_exit_price is not None:
            ce_pnl = (ce_entry_price - ce_exit_price) * lot_size * lot_multiple
        if trade_pe and pe_entry_price is not None and pe_exit_price is not None:
            pe_pnl = (pe_entry_price - pe_exit_price) * lot_size * lot_multiple
        total_pnl = ce_pnl + pe_pnl
        
        # Determine primary entry time for record (earliest leg entry)
        primary_entry_time = ce_entry_time if trade_ce else None
        if trade_pe:
            if primary_entry_time is None or pe_entry_time < primary_entry_time:
                primary_entry_time = pe_entry_time
        
        # Use Nifty at actual primary entry time for display / reasoning
        trade_nifty_entry = get_nifty_price_at_time(nifty_data, date_str, primary_entry_time) or nifty_entry_price
        
        # Build result for this day (at most one trade per leg, no re-entries)
        result = {
            "date": date_str,
            "trade_number": 1,
            "entry_time": f"{date_str} {primary_entry_time}",
            "exit_time": f"{date_str} {exit_time}",
            "entry_reason": entry_reason,
            "fast_ema_at_entry": round(fast_ema_value, 2) if fast_ema_value is not None else None,
            "slow_ema_at_entry": round(slow_ema_value, 2) if slow_ema_value is not None else None,
            "fast_ema_at_exit": round(fast_ema_exit, 2) if fast_ema_exit is not None else None,
            "slow_ema_at_exit": round(slow_ema_exit, 2) if slow_ema_exit is not None else None,
            "expiry_date": expiry_date,
            "vix_at_entry": round(vix_at_entry, 2) if vix_at_entry is not None else None,
            "vix_at_exit": None,
            "nifty_entry_price": round(trade_nifty_entry, 2) if trade_nifty_entry else None,
            "nifty_exit_price": round(nifty_exit_price, 2) if nifty_exit_price else None,
            "ce_strike": ce_strike,
            "ce_entry_price": round(ce_entry_price, 2) if ce_entry_price is not None else None,
            "ce_entry_time": f"{date_str} {ce_entry_time}" if trade_ce and ce_entry_time else None,
            "ce_exit_price": round(ce_exit_price, 2) if ce_exit_price is not None else None,
            "ce_exit_time": f"{date_str} {exit_time}" if trade_ce else None,
            "ce_exit_reason": "SCHEDULED_EXIT" if trade_ce else None,
            "ce_stopped": False,
            "ce_pnl": round(ce_pnl, 2),
            "pe_strike": pe_strike,
            "pe_entry_price": round(pe_entry_price, 2) if pe_entry_price is not None else None,
            "pe_entry_time": f"{date_str} {pe_entry_time}" if trade_pe and pe_entry_time else None,
            "pe_exit_price": round(pe_exit_price, 2) if pe_exit_price is not None else None,
            "pe_exit_time": f"{date_str} {exit_time}" if trade_pe else None,
            "pe_exit_reason": "SCHEDULED_EXIT" if trade_pe else None,
            "pe_stopped": False,
            "pe_pnl": round(pe_pnl, 2),
            "total_pnl": round(total_pnl, 2)
        }
        
        results.append(result)
        
        # Print trade details
        ce_info = "CE: N/A"
        pe_info = "PE: N/A"
        if trade_ce and ce_strike is not None:
            ce_info = f"CE Strike {ce_strike}: Entry {ce_entry_price}, Exit {ce_exit_price} at {exit_time} (SCHEDULED_EXIT), P&L: {ce_pnl}"
        if trade_pe and pe_strike is not None:
            pe_info = f"PE Strike {pe_strike}: Entry {pe_entry_price}, Exit {pe_exit_price} at {exit_time} (SCHEDULED_EXIT), P&L: {pe_pnl}"
        print(f"  Trade: {ce_info}")
        print(f"  Trade: {pe_info}")
        print(f"    Total P&L: {total_pnl}")
        
        current_date += timedelta(days=1)
    
    return results


def calculate_drawdown_metrics(results: List[Dict]) -> tuple:
    """Calculate max drawdown and max drawdown days from results"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED, EMA_NEUTRAL) for drawdown calculation
    actual_trades = [r for r in results if r.get('entry_reason') not in ['VIX_THRESHOLD_EXCEEDED', 'EMA_NEUTRAL']]
    
    if not actual_trades:
        return 0.0, 0
    
    # Calculate cumulative P&L for each trade day
    cumulative_pnl = []
    cumsum = 0
    for r in actual_trades:
        cumsum += r.get('ce_pnl', 0) + r.get('pe_pnl', 0)
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


def save_results(results: List[Dict], output_file: str, per_order_charges: float = 0.0, lot_multiple: int = 1):
    """Save backtest results to JSON file"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED and EMA_NEUTRAL) for trade statistics
    actual_trades = [r for r in results if r.get('entry_reason') not in ['VIX_THRESHOLD_EXCEEDED', 'EMA_NEUTRAL']]
    
    max_drawdown, max_drawdown_days = calculate_drawdown_metrics(results)
    
    # Calculate total orders - each trade row now represents a single trade pair
    # Each trade has 2 legs (CE + PE), each leg has entry + exit = 4 orders per trade
    # But some trades may only have one leg active
    total_orders = 0
    total_reentries = 0
    for r in actual_trades:
        # Count orders for this trade
        if r.get('ce_strike') is not None:
            total_orders += 2  # CE entry + exit
        if r.get('pe_strike') is not None:
            total_orders += 2  # PE entry + exit
        # Count re-entries (trades after trade_number 1)
        if r.get('trade_number', 1) > 1:
            total_reentries += 1
    
    total_charges = total_orders * per_order_charges
    
    # Calculate net P&L after charges (only for actual trades)
    total_pnl = round(sum(r['total_pnl'] for r in actual_trades), 2)
    net_pnl = round(total_pnl - total_charges, 2)
    
    # Total trading days = unique dates in results
    unique_dates = set(r['date'] for r in results)
    total_trading_days = len(unique_dates)
    
    summary = {
        "total_trading_days": total_trading_days,
        "total_trades": len(actual_trades),
        "total_reentries": total_reentries,
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
    print(f"Total Re-entries: {summary['total_reentries']}")
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

