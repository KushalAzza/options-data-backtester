#!/usr/bin/env python3
"""
Nifty Options Positional Backtest Script
Backtests ATM CE and PE options strategy for positional trading (hold until expiry or target/stop loss)
Exits on expiry date or when target percentage is reached or stop loss is hit
Only runs when use_positional is true in config.json
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import math
from utils.db_utils import save_backtest_history


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


def round_time_to_interval(time_str: str, interval_minutes: int) -> str:
    """
    Floor time string down to the start of its interval boundary.
    
    Args:
        time_str: Time in "HH:MM:SS" format
        interval_minutes: Interval in minutes (e.g., 15 for :00, :15, :30, :45)
    
    Returns:
        Rounded time string in "HH:MM:SS" format
    """
    try:
        # Parse time string (using a dummy date for datetime parsing)
        time_obj = datetime.strptime(f"2000-01-01 {time_str}", "%Y-%m-%d %H:%M:%S")
        
        # Calculate total minutes from midnight
        total_minutes = time_obj.hour * 60 + time_obj.minute
        
        # Floor to interval (e.g. 09:18 -> 09:15 for 5-min interval)
        floored_minutes = (total_minutes // interval_minutes) * interval_minutes
        
        floored_hour = (floored_minutes // 60) % 24
        floored_min = floored_minutes % 60
        
        # Create new datetime object and format (seconds set to 0)
        rounded_time = time_obj.replace(hour=floored_hour, minute=floored_min, second=0, microsecond=0)
        
        return rounded_time.strftime("%H:%M:%S")
    except:
        # If parsing fails, return original time
        return time_str


def get_price_at_time(data: List[Dict], target_time: str) -> Optional[float]:
    """Get open price at specific time from minute-level data"""
    for entry in data:
        if entry.get('datetime', entry.get('time', '')).startswith(target_time[:10] + ' ' + target_time[11:]):
            return entry.get('open')
    return None


def get_nifty_price_at_time(nifty_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get Nifty open price at specific date and time"""
    date_key = date
    if date_key not in nifty_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in nifty_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('open')
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
    
    # Get current open price
    current_open = get_nifty_price_at_time(nifty_data, date, time_str)
    
    if current_open is None:
        return None, fast_ema, slow_ema
    
    # Determine signal
    if fast_ema > slow_ema and current_open > fast_ema and current_open > slow_ema:
        return 'BULLISH', fast_ema, slow_ema
    if fast_ema < slow_ema and current_open < fast_ema and current_open < slow_ema:
        return 'BEARISH', fast_ema, slow_ema
    
    return None, fast_ema, slow_ema  # NEUTRAL


def find_ema_entry_times(
    nifty_data: Dict,
    date: str,
    entry_time: str,
    exit_time: str,
    interval_minutes: int,
    no_entry_after: Optional[str] = None,
    round_to_interval: bool = False,
    use_ema_cross_entry: bool = False
) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
    """
    Find first EMA-based entry times for CE and PE independently between entry_time and exit_time.
    
    When use_ema_cross_entry is False (default):
    - CE entry (BEARISH): F < S, N < F, N < S  -> SHORT CE
    - PE entry (BULLISH): F > S, N > F, N > S  -> SHORT PE
    
    When use_ema_cross_entry is True:
    - CE entry (BEARISH CROSSOVER): Fast EMA crosses below Slow EMA (F was >= S, now F < S) AND N < F AND N < S -> SHORT CE
    - PE entry (BULLISH CROSSOVER): Fast EMA crosses above Slow EMA (F was <= S, now F > S) AND N > F AND N > S -> SHORT PE
    
    Args:
        no_entry_after: If provided, stop checking for entries after this time (format: 'HH:MM:SS')
        round_to_interval: If True, only check at exact interval boundaries (e.g., 9:15, 9:20, 9:25 for 5-min)
                          If False, check at every minute
        use_ema_cross_entry: If True, require EMA crossover for entry. If False, use current EMA setup.
    
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
    
    # Calculate no_entry_after datetime if provided
    no_entry_after_dt = None
    if no_entry_after:
        try:
            no_entry_after_dt = datetime.strptime(f"{date} {no_entry_after}", "%Y-%m-%d %H:%M:%S")
        except:
            pass  # If parsing fails, ignore the limit
    
    # If round_to_interval is enabled, start from the first interval boundary at or after entry_time
    if round_to_interval:
        # Floor entry_time to interval boundary
        entry_minutes = entry_dt.hour * 60 + entry_dt.minute
        floored_minutes = (entry_minutes // interval_minutes) * interval_minutes
        # If entry_time is not already at a boundary, move to next boundary
        if entry_minutes % interval_minutes != 0:
            floored_minutes += interval_minutes
        floored_hour = (floored_minutes // 60) % 24
        floored_min = floored_minutes % 60
        current_dt = entry_dt.replace(hour=floored_hour, minute=floored_min, second=0, microsecond=0)
        increment_minutes = interval_minutes
    else:
        # When not rounding, check at every minute
        current_dt = entry_dt
        increment_minutes = 1
    
    # Determine the effective end time (minimum of exit_time and no_entry_after)
    effective_end_dt = exit_dt
    if no_entry_after_dt and no_entry_after_dt < exit_dt:
        effective_end_dt = no_entry_after_dt
    
    # For crossover detection, we need to track previous EMA relationship
    prev_fast_ema: Optional[float] = None
    prev_slow_ema: Optional[float] = None
    
    while current_dt <= effective_end_dt and (ce_entry_time is None or pe_entry_time is None):
        time_str = current_dt.strftime("%H:%M:%S")
        
        fast_ema, slow_ema = get_ema_from_nifty_data(nifty_data, date, time_str)
        if fast_ema is None or slow_ema is None:
            current_dt += timedelta(minutes=increment_minutes)
            continue
        
        price = get_nifty_price_at_time(nifty_data, date, time_str)
        if price is None:
            current_dt += timedelta(minutes=increment_minutes)
            continue
        
        if use_ema_cross_entry:
            # Crossover mode: require EMA crossover along with price conditions
            # Need previous EMA values to detect crossover
            if prev_fast_ema is not None and prev_slow_ema is not None:
                # Check for BEARISH crossover: Fast EMA crosses below Slow EMA
                # Previous: fast_ema >= slow_ema, Current: fast_ema < slow_ema
                prev_bearish = prev_fast_ema >= prev_slow_ema
                curr_bearish = fast_ema < slow_ema
                bearish_crossover = prev_bearish and curr_bearish
                
                # Check for BULLISH crossover: Fast EMA crosses above Slow EMA
                # Previous: fast_ema <= slow_ema, Current: fast_ema > slow_ema
                prev_bullish = prev_fast_ema <= prev_slow_ema
                curr_bullish = fast_ema > slow_ema
                bullish_crossover = prev_bullish and curr_bullish
                
                # BEARISH CROSSOVER: F crosses below S AND N < F AND N < S -> SHORT CE
                if ce_entry_time is None and bearish_crossover and price < fast_ema and price < slow_ema:
                    ce_entry_time = time_str
                    if first_fast_ema is None:
                        first_fast_ema = fast_ema
                        first_slow_ema = slow_ema
                
                # BULLISH CROSSOVER: F crosses above S AND N > F AND N > S -> SHORT PE
                if pe_entry_time is None and bullish_crossover and price > fast_ema and price > slow_ema:
                    pe_entry_time = time_str
                    if first_fast_ema is None:
                        first_fast_ema = fast_ema
                        first_slow_ema = slow_ema
            else:
                # First iteration - no previous values, so no crossover can be detected yet
                # Store current values for next iteration
                prev_fast_ema = fast_ema
                prev_slow_ema = slow_ema
                current_dt += timedelta(minutes=increment_minutes)
                continue
        else:
            # Original mode: just check current EMA relationship and price
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
        
        # Update previous values for next iteration (only needed for crossover mode, but harmless otherwise)
        prev_fast_ema = fast_ema
        prev_slow_ema = slow_ema
        
        current_dt += timedelta(minutes=increment_minutes)
    
    return ce_entry_time, pe_entry_time, first_fast_ema, first_slow_ema


def get_vix_price_at_time(vix_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get India VIX open price at specific date and time"""
    date_key = date
    if date_key not in vix_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in vix_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('open')
    return None


def get_vix_base_ema_at_time(vix_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get India VIX base_ema at specific date and time"""
    date_key = date
    if date_key not in vix_data:
        return None
    
    target_time = f"{date} {time_str}"
    for entry in vix_data[date_key]:
        if entry.get('time') == target_time:
            return entry.get('base_ema')
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
            return entry.get('open')
    
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
                closest_price = entry.get('open')
        except:
            continue
    
    return closest_price


def check_ema_exit_condition(nifty_data: Dict, date: str, entry_time: str, exit_time: str,
                              is_bullish: bool, interval_minutes: int) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[float]]:
    """
    Check if EMA-based exit condition is met between entry and exit times.
    Uses pre-calculated EMA values from nifty_intraday_price.json.
    
    For BULLISH trade (PE): exit when N < F AND N < S
    For BEARISH trade (CE): exit when N > F AND N > S
    
    Returns: (exit_time, nifty_price, fast_ema_value, slow_ema_value) or (None, None, None, None) if not triggered
    """
    entry_datetime = datetime.strptime(f"{date} {entry_time}", "%Y-%m-%d %H:%M:%S")
    exit_datetime = datetime.strptime(f"{date} {exit_time}", "%Y-%m-%d %H:%M:%S")
    
    # Check at interval boundaries between entry and exit
    # Start checking at first interval after entry to avoid immediate exit
    current_time = entry_datetime + timedelta(minutes=interval_minutes)
    
    while current_time <= exit_datetime:
        time_str = current_time.strftime("%H:%M:%S")
        
        # Get pre-calculated EMA values from nifty data
        fast_ema, slow_ema = get_ema_from_nifty_data(nifty_data, date, time_str)
        if fast_ema is None or slow_ema is None:
            current_time += timedelta(minutes=interval_minutes)
            continue
        
        # Get Nifty open price at this time
        nifty_price = get_nifty_price_at_time(nifty_data, date, time_str)
        if nifty_price is None:
            current_time += timedelta(minutes=interval_minutes)
            continue
        
        # Check exit conditions
        if is_bullish:
            # BULLISH (PE): Exit when N < F AND N < S
            if nifty_price < fast_ema and nifty_price < slow_ema:
                return time_str, nifty_price, fast_ema, slow_ema
        else:
            # BEARISH (CE): Exit when N > F AND N > S
            if nifty_price > fast_ema and nifty_price > slow_ema:
                return time_str, nifty_price, fast_ema, slow_ema
        
        current_time += timedelta(minutes=interval_minutes)
    
    return None, None, None, None


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
            price = entry.get('open')
            
            # Only check times between entry and exit
            if entry_datetime <= price_datetime <= exit_datetime:
                # For SHORT: stop loss triggers when price >= stop_loss_price
                if price is not None and price >= stop_loss_price:
                    return price, entry_datetime_str.split(' ')[1]  # Return time part only
        except:
            continue
    
    return None, None


def check_target_profit(options_data: Dict, option_type: str, strike: int, entry_time: str, 
                        exit_time: str, entry_price: float, target_percentage: float) -> Tuple[Optional[float], Optional[str]]:
    """
    Check if target profit is hit between entry and exit times.
    For SHORT positions: target profit triggers when price decreases by target_percentage.
    Returns: (target_exit_price, target_exit_time) or (None, None) if not hit
    """
    if target_percentage <= 0 or entry_price is None:
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
    
    # Calculate target profit price (for SHORT: price goes DOWN by target_percentage)
    target_price = entry_price * (1 - target_percentage / 100)
    
    # Check prices between entry and exit times
    for entry in strike_data:
        entry_datetime_str = entry.get('datetime')
        if not entry_datetime_str:
            continue
        
        try:
            price_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
            price = entry.get('open')
            
            # Only check times between entry and exit
            if entry_datetime <= price_datetime <= exit_datetime:
                # For SHORT: target profit triggers when price <= target_price
                if price is not None and price <= target_price:
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


def is_cooldown_passed(exit_time: str, reentry_time: str, exit_reason: str, 
                       cooldown_minutes: int, date_str: str) -> bool:
    """
    Check if stop-loss cooldown period has passed.
    Returns True if cooldown has passed or if exit was not due to stop loss.
    
    Args:
        exit_time: Exit time in "HH:MM:SS" format
        reentry_time: Potential re-entry time in "HH:MM:SS" format
        exit_reason: Reason for exit (e.g., "STOP_LOSS", "TARGET_HIT", "EMA_EXIT", "SCHEDULED_EXIT")
        cooldown_minutes: Cooldown period in minutes
        date_str: Date string in "YYYY-MM-DD" format
    
    Returns:
        True if cooldown has passed or exit was not due to stop loss, False otherwise
    """
    # If exit was not due to stop loss, no cooldown applies
    if exit_reason != "STOP_LOSS":
        return True
    
    # If cooldown is 0 or negative, no cooldown applies
    if cooldown_minutes <= 0:
        return True
    
    try:
        # Parse exit and re-entry times
        exit_datetime = datetime.strptime(f"{date_str} {exit_time}", "%Y-%m-%d %H:%M:%S")
        reentry_datetime = datetime.strptime(f"{date_str} {reentry_time}", "%Y-%m-%d %H:%M:%S")
        
        # Calculate time difference
        time_diff = reentry_datetime - exit_datetime
        time_diff_minutes = time_diff.total_seconds() / 60
        
        # Check if cooldown period has passed
        return time_diff_minutes >= cooldown_minutes
    except:
        # If parsing fails, allow re-entry (fail open)
        return True


def parse_expiry_date(expiry_date_str: str) -> Optional[datetime]:
    """
    Parse expiry date from "DD-MMM-YYYY" format to datetime object.
    Example: "10-JUL-2025" -> datetime(2025, 7, 10)
    """
    try:
        # Parse "DD-MMM-YYYY" format
        return datetime.strptime(expiry_date_str, "%d-%b-%Y")
    except:
        try:
            # Try alternative format "DD-MMM-YY"
            return datetime.strptime(expiry_date_str, "%d-%b-%y")
        except:
            return None


def get_option_price_on_date(options_data_path: str, option_type: str, strike: int, 
                             date_str: str, time_str: str) -> Optional[float]:
    """
    Get option price on a specific date and time.
    Loads the options data file for the given date if needed.
    
    Args:
        options_data_path: Base path to options data directory (e.g., "data")
        option_type: 'CE' or 'PE'
        strike: Strike price
        date_str: Date in "YYYY-MM-DD" format
        time_str: Time in "HH:MM:SS" format
    
    Returns:
        Option price or None if not found
    """
    year = datetime.strptime(date_str, "%Y-%m-%d").year
    options_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
    
    options_data = load_options_data(options_file)
    if not options_data:
        return None
    
    return get_option_price_closest(options_data, option_type, strike, time_str)


def check_target_profit_positional(options_data_path: str, option_type: str, strike: int,
                                   entry_date: str, entry_time: str, entry_price: float,
                                   target_percentage: float, expiry_date: datetime,
                                   use_next_expiry: bool = False) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Check if target profit is hit across multiple days until expiry (for positional trades).
    For SHORT positions: target profit triggers when price decreases by target_percentage.
    Optimized: Iterates through actual option price entries instead of checking every minute.
    
    Args:
        options_data_path: Base path to options data directory
        option_type: 'CE' or 'PE'
        strike: Strike price
        entry_date: Entry date in "YYYY-MM-DD" format
        entry_time: Entry time in "HH:MM:SS" format
        entry_price: Entry price
        target_percentage: Target profit percentage
        expiry_date: Expiry date as datetime object
    
    Returns:
        (target_exit_price, target_exit_date, target_exit_time) or (None, None, None) if not hit
    """
    if target_percentage <= 0 or entry_price is None:
        return None, None, None
    
    # Calculate target profit price (for SHORT: price goes DOWN by target_percentage)
    target_price = entry_price * (1 - target_percentage / 100)
    
    # Parse entry datetime
    entry_datetime = datetime.strptime(f"{entry_date} {entry_time}", "%Y-%m-%d %H:%M:%S")
    expiry_date_only = expiry_date.date()
    
    # Iterate through trading days from entry date until expiry
    current_date = entry_datetime.date()
    
    while current_date <= expiry_date_only:
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        date_str = current_date.strftime("%Y-%m-%d")
        year = current_date.year
        
        # Determine options file (handle use_next_expiry)
        if use_next_expiry:
            next_expiry_file = f"{options_data_path}/{year}/nifty_options_{date_str}_next_expiry.json"
            regular_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
            if os.path.exists(next_expiry_file):
                options_file = next_expiry_file
            else:
                options_file = regular_file
        else:
            options_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
        
        options_data = load_options_data(options_file)
        if not options_data:
            current_date += timedelta(days=1)
            continue
        
        # Get option section
        option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
        if not option_section:
            current_date += timedelta(days=1)
            continue
        
        strike_key = str(strike)
        if strike_key not in option_section:
            current_date += timedelta(days=1)
            continue
        
        strike_data = option_section[strike_key]
        
        # Iterate through actual price entries for this strike
        for entry in strike_data:
            entry_datetime_str = entry.get('datetime')
            if not entry_datetime_str:
                continue
            
            try:
                price_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
                price = entry.get('open')
                
                # Only check prices after entry time
                if price_datetime <= entry_datetime:
                    continue
                
                # Only check prices before or on expiry date
                if price_datetime.date() > expiry_date_only:
                    break
                
                # Check if target is hit
                if price is not None and price <= target_price:
                    exit_date = price_datetime.strftime("%Y-%m-%d")
                    exit_time = price_datetime.strftime("%H:%M:%S")
                    return price, exit_date, exit_time
            except:
                continue
        
        current_date += timedelta(days=1)
    
    return None, None, None


def check_ema_exit_condition_positional(nifty_data: Dict, entry_date: str, entry_time: str,
                                        expiry_date: datetime, is_bullish: bool,
                                        interval_minutes: int) -> Tuple[Optional[str], Optional[str], Optional[float], Optional[float], Optional[float]]:
    """
    Check if EMA-based exit condition is met across multiple days until expiry (for positional trades).
    Uses pre-calculated EMA values from nifty_intraday_price.json.
    
    For BULLISH trade (PE): exit when N < F AND N < S
    For BEARISH trade (CE): exit when N > F AND N > S
    
    Args:
        nifty_data: Nifty intraday data dictionary
        entry_date: Entry date in "YYYY-MM-DD" format
        entry_time: Entry time in "HH:MM:SS" format
        expiry_date: Expiry date as datetime object
        is_bullish: True for BULLISH (PE) trade, False for BEARISH (CE) trade
        interval_minutes: Interval in minutes for checking EMA conditions
    
    Returns:
        (exit_date, exit_time, nifty_price, fast_ema_value, slow_ema_value) or (None, None, None, None, None) if not triggered
    """
    entry_datetime = datetime.strptime(f"{entry_date} {entry_time}", "%Y-%m-%d %H:%M:%S")
    expiry_date_only = expiry_date.date()
    
    # Start checking at first interval after entry to avoid immediate exit
    current_datetime = entry_datetime + timedelta(minutes=interval_minutes)
    current_date = current_datetime.date()
    
    while current_date <= expiry_date_only:
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            if current_date > expiry_date_only:
                break
            # Reset to start of trading day (09:15) on next trading day
            current_datetime = datetime.combine(current_date, datetime.strptime("09:15:00", "%H:%M:%S").time())
            continue
        
        date_str = current_date.strftime("%Y-%m-%d")
        time_str = current_datetime.strftime("%H:%M:%S")
        
        # Get pre-calculated EMA values from nifty data
        fast_ema, slow_ema = get_ema_from_nifty_data(nifty_data, date_str, time_str)
        if fast_ema is None or slow_ema is None:
            current_datetime += timedelta(minutes=interval_minutes)
            # Update current_date if we've moved to next day
            if current_datetime.date() != current_date:
                current_date = current_datetime.date()
            continue
        
        # Get Nifty open price at this time
        nifty_price = get_nifty_price_at_time(nifty_data, date_str, time_str)
        if nifty_price is None:
            current_datetime += timedelta(minutes=interval_minutes)
            # Update current_date if we've moved to next day
            if current_datetime.date() != current_date:
                current_date = current_datetime.date()
            continue
        
        # Check exit conditions
        if is_bullish:
            # BULLISH (PE): Exit when N < F AND N < S
            if nifty_price < fast_ema and nifty_price < slow_ema:
                exit_date = date_str
                exit_time = time_str
                return exit_date, exit_time, nifty_price, fast_ema, slow_ema
        else:
            # BEARISH (CE): Exit when N > F AND N > S
            if nifty_price > fast_ema and nifty_price > slow_ema:
                exit_date = date_str
                exit_time = time_str
                return exit_date, exit_time, nifty_price, fast_ema, slow_ema
        
        # Move to next interval
        current_datetime += timedelta(minutes=interval_minutes)
        
        # Update current_date if we've moved to next day
        if current_datetime.date() != current_date:
            current_date = current_datetime.date()
        
        # If we've passed end of trading day (15:30), move to next day
        if current_datetime.hour >= 15 and current_datetime.minute >= 30:
            current_date += timedelta(days=1)
            if current_date > expiry_date_only:
                break
            # Reset to start of trading day (09:15)
            current_datetime = datetime.combine(current_date, datetime.strptime("09:15:00", "%H:%M:%S").time())
    
    return None, None, None, None, None


def check_stop_loss_positional(options_data_path: str, option_type: str, strike: int,
                                entry_date: str, entry_time: str, entry_price: float,
                                stop_loss_percentage: float, expiry_date: datetime,
                                use_next_expiry: bool = False) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Check if stop loss is hit across multiple days until expiry (for positional trades).
    For SHORT positions: stop loss triggers when price increases by stop_loss_percentage.
    Optimized: Iterates through actual option price entries instead of checking every minute.
    
    Args:
        options_data_path: Base path to options data directory
        option_type: 'CE' or 'PE'
        strike: Strike price
        entry_date: Entry date in "YYYY-MM-DD" format
        entry_time: Entry time in "HH:MM:SS" format
        entry_price: Entry price
        stop_loss_percentage: Stop loss percentage
        expiry_date: Expiry date as datetime object
    
    Returns:
        (stop_loss_exit_price, stop_loss_exit_date, stop_loss_exit_time) or (None, None, None) if not hit
    """
    if stop_loss_percentage <= 0 or entry_price is None:
        return None, None, None
    
    # Calculate stop loss price (for SHORT: price goes UP by stop_loss_percentage)
    stop_loss_price = entry_price * (1 + stop_loss_percentage / 100)
    
    # Parse entry datetime
    entry_datetime = datetime.strptime(f"{entry_date} {entry_time}", "%Y-%m-%d %H:%M:%S")
    expiry_date_only = expiry_date.date()
    
    # Iterate through trading days from entry date until expiry
    current_date = entry_datetime.date()
    
    while current_date <= expiry_date_only:
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        date_str = current_date.strftime("%Y-%m-%d")
        year = current_date.year
        
        # Determine options file (handle use_next_expiry)
        if use_next_expiry:
            next_expiry_file = f"{options_data_path}/{year}/nifty_options_{date_str}_next_expiry.json"
            regular_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
            if os.path.exists(next_expiry_file):
                options_file = next_expiry_file
            else:
                options_file = regular_file
        else:
            options_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
        
        options_data = load_options_data(options_file)
        if not options_data:
            current_date += timedelta(days=1)
            continue
        
        # Get option section
        option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
        if not option_section:
            current_date += timedelta(days=1)
            continue
        
        strike_key = str(strike)
        if strike_key not in option_section:
            current_date += timedelta(days=1)
            continue
        
        strike_data = option_section[strike_key]
        
        # Iterate through actual price entries for this strike
        for entry in strike_data:
            entry_datetime_str = entry.get('datetime')
            if not entry_datetime_str:
                continue
            
            try:
                price_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
                price = entry.get('open')
                
                # Only check prices after entry time
                if price_datetime <= entry_datetime:
                    continue
                
                # Only check prices before or on expiry date
                if price_datetime.date() > expiry_date_only:
                    break
                
                # Check if stop loss is hit
                if price is not None and price >= stop_loss_price:
                    exit_date = price_datetime.strftime("%Y-%m-%d")
                    exit_time = price_datetime.strftime("%H:%M:%S")
                    return price, exit_date, exit_time
            except:
                continue
        
        current_date += timedelta(days=1)
    
    return None, None, None


def run_backtest(config: Dict) -> List[Dict]:
    """Run positional backtest for specified period"""
    results = []
    
    # Check if positional trading is enabled
    use_positional = config.get('backtest_period', {}).get('use_positional', False)
    if not use_positional:
        print("ERROR: use_positional must be true in config.json to use run_positional_backtest.py")
        print("Please set 'use_positional': true in config.json['backtest_period'] or use run_intraday_backtest.py instead")
        return results
    
    # Get no_existing_trades setting
    no_existing_trades = config.get('backtest_period', {}).get('no_existing_trades', False)
    
    # Load data
    nifty_data = load_nifty_intraday(config['data_paths']['nifty_intraday'])
    
    # Load VIX data if path is configured
    vix_data = None
    vix_threshold = config['options'].get('vix_threshold', None)
    vix_ema_signal = config['options'].get('vix_ema_signal', False)
    if (vix_threshold is not None or vix_ema_signal) and 'vix_intraday' in config['data_paths']:
        vix_data = load_vix_intraday(config['data_paths']['vix_intraday'])
    
    # Parse dates
    start_date = datetime.strptime(config['backtest_period']['start_date'], "%Y-%m-%d")
    end_date = datetime.strptime(config['backtest_period']['end_date'], "%Y-%m-%d")
    
    entry_time = config['trading_times']['entry_time']
    exit_time = config['trading_times']['exit_time']
    no_entry_after = config['trading_times'].get('no_entry_after', None)  # Time after which no first entry allowed
    
    strike_rounding = config['basic_settings']['strike_rounding']
    ce_offset = config['basic_settings']['ce_strike_offset']
    pe_offset = config['basic_settings']['pe_strike_offset']
    lot_size = config['basic_settings']['lot_size']
    lot_multiple = config['basic_settings'].get('lot_multiple', 1)
    use_next_expiry = config['basic_settings']['use_next_expiry']
    per_order_charges = config['basic_settings'].get('per_order_charges', 100)
    stop_loss_percentage = config['options'].get('stop_loss_percentage', 0)
    target_percentage = config['options'].get('target_percentage', 0)
    
    # EMA signal configuration
    ema_enabled = config.get('ema_signals', {}).get('enabled', False)
    use_ema_exit = config.get('ema_signals', {}).get('use_ema_exit', True)
    ema_interval = config.get('ema_signals', {}).get('time_interval', 15)
    ema_fast = config.get('ema_signals', {}).get('fast_ema', 9)
    ema_slow = config.get('ema_signals', {}).get('slow_ema', 21)
    round_to_ema_interval = config.get('ema_signals', {}).get('round_to_ema_interval', False)
    use_ema_cross_entry = config.get('ema_signals', {}).get('use_ema_cross_entry', False)
    
    # Re-entry configuration for positional trades
    # Re-entry is only allowed when BOTH CE and PE legs have been exited
    reentry_enabled = config.get('reentry', {}).get('enabled', False)
    max_reentries = config.get('reentry', {}).get('max_reentries', 0)
    no_reentry_after = config.get('reentry', {}).get('no_reentry_after', None)  # Time after which no re-entry allowed
    stop_loss_cooldown_minutes = config.get('reentry', {}).get('stop_loss_cooldown_minutes', 0)  # Cooldown period after stop loss
    reentry_based_on_ema_signals = config.get('reentry', {}).get('reentry_based_on_ema_signals', False)  # Require EMA conditions for reentry
    
    # Track open positions for positional trading
    # Format: {leg_type: {"entry_date": str, "entry_time": str, "exit_date": str, "exit_time": str, "strike": int, "expiry_date": datetime}}
    open_ce_position = None
    open_pe_position = None
    
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
        if use_next_expiry:
            # When use_next_expiry is true, try to use the _next_expiry file first
            # If it doesn't exist, fall back to the regular file
            next_expiry_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}_next_expiry.json"
            regular_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}.json"
            
            if os.path.exists(next_expiry_file):
                options_file = next_expiry_file
            else:
                # Fall back to regular file if _next_expiry doesn't exist
                options_file = regular_file
        else:
            # When use_next_expiry is false, use the regular file (same day expiry)
            options_file = f"{config['data_paths']['options_data']}/{year}/nifty_options_{date_str}.json"
        
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
        
        # Check VIX threshold if configured (check at entry_time)
        entry_reason = "NORMAL"
        if vix_data is not None:
            # Check VIX threshold
            if vix_threshold is not None:
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
                        "vix_at_exit": round(vix_entry_price, 2),
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
                nifty_data, date_str, entry_time, exit_time, ema_interval, no_entry_after, round_to_ema_interval, use_ema_cross_entry
            )
            
            # When round_to_ema_interval is enabled, entry times are already at interval boundaries
            # No additional rounding needed
            
            trade_ce = ce_entry_time is not None
            trade_pe = pe_entry_time is not None
            
        else:
            # When EMA is not enabled, round entry_time to interval if round_to_ema_interval is enabled
            if round_to_ema_interval:
                ce_entry_time = round_time_to_interval(entry_time, ema_interval)
                pe_entry_time = round_time_to_interval(entry_time, ema_interval)
            # When EMA is disabled, we trade both legs by default
            trade_ce = True
            trade_pe = True
        
        # Check VIX EMA signal at interval boundaries (independent of EMA signals enabled/disabled)
        # VIX EMA signal only depends on vix_ema_signal config, not on ema_enabled
        # NOTE: This check only runs when entry_reason is "NORMAL", which happens in non-EMA mode
        # In EMA mode, entry_reason is set later, so this check is skipped
        if entry_reason == "NORMAL" and vix_ema_signal and vix_data is not None:
            # Check VIX EMA signal for CE entry time
            if trade_ce and ce_entry_time is not None:
                vix_ce_price = get_vix_price_at_time(vix_data, date_str, ce_entry_time)
                vix_ce_base_ema = get_vix_base_ema_at_time(vix_data, date_str, ce_entry_time)
                if vix_ce_price is not None and vix_ce_base_ema is not None and vix_ce_price > vix_ce_base_ema:
                    print(f"  VIX EMA signal blocked for CE: VIX price ({vix_ce_price:.2f}) > base_ema ({vix_ce_base_ema:.2f}) at {ce_entry_time}, blocking CE entry")
                    trade_ce = False
                    ce_entry_time = None
            
            # Check VIX EMA signal for PE entry time
            if trade_pe and pe_entry_time is not None:
                vix_pe_price = get_vix_price_at_time(vix_data, date_str, pe_entry_time)
                vix_pe_base_ema = get_vix_base_ema_at_time(vix_data, date_str, pe_entry_time)
                if vix_pe_price is not None and vix_pe_base_ema is not None and vix_pe_price > vix_pe_base_ema:
                    print(f"  VIX EMA signal blocked for PE: VIX price ({vix_pe_price:.2f}) > base_ema ({vix_pe_base_ema:.2f}) at {pe_entry_time}, blocking PE entry")
                    trade_pe = False
                    pe_entry_time = None
            
            # If both legs are blocked, skip the entire trade
            if not trade_ce and not trade_pe:
                entry_reason = "VIX_EMA_SIGNAL_BLOCKED"
                expiry_date = options_data.get('expiry_date', None)
                vix_entry_price = get_vix_price_at_time(vix_data, date_str, entry_time) if vix_data else None
                result = {
                    "date": date_str,
                    "entry_time": f"{date_str} {entry_time}",
                    "exit_time": f"{date_str} {entry_time}",
                    "entry_reason": entry_reason,
                    "fast_ema_at_entry": None,
                    "slow_ema_at_entry": None,
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
        
        # EMA signal logic - this should run when ema_enabled is True, regardless of VIX check
        if ema_enabled:
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
            mode_str = "CROSSOVER" if use_ema_cross_entry else "STANDARD"
            if trade_ce and trade_pe:
                entry_reason = "EMA_MIXED"
                print(f"  EMA Signals ({mode_str}): CE (BEARISH) at {ce_entry_time}, PE (BULLISH) at {pe_entry_time} - entering both legs")
            elif trade_ce and not trade_pe:
                # CE comes from BEARISH EMA conditions
                entry_reason = "EMA_BEARISH"
                print(f"  EMA Signal ({mode_str}): BEARISH - Short CE only (first entry at {ce_entry_time})")
            elif trade_pe and not trade_ce:
                # PE comes from BULLISH EMA conditions
                entry_reason = "EMA_BULLISH"
                print(f"  EMA Signal ({mode_str}): BULLISH - Short PE only (first entry at {pe_entry_time})")
            else:
                # Neither leg has valid signal - should not happen, but handle gracefully
                entry_reason = "NO_SIGNAL"
                print(f"  WARNING: No valid EMA signals found for {date_str}")
        else:
            # Non-EMA mode: trade both legs from configured entry_time
            trade_ce = True
            trade_pe = True
            ce_entry_time = entry_time
            pe_entry_time = entry_time
            # Round entry times to ema_interval if enabled
            if round_to_ema_interval:
                ce_entry_time = round_time_to_interval(ce_entry_time, ema_interval)
                pe_entry_time = round_time_to_interval(pe_entry_time, ema_interval)
            entry_reason = "NORMAL"
        
        # Check for open positions from previous days before opening new trades
        # If there's an open position, we should not open a new trade for that leg
        # Use entry_time as the reference time for checking (we check at the start of the day)
        check_datetime = datetime.combine(current_date, datetime.strptime(entry_time, "%H:%M:%S").time())
        
        # Track exits that happen today (for re-entry logic)
        ce_exit_today = None  # (exit_time, exit_reason) if CE exited today
        pe_exit_today = None  # (exit_time, exit_reason) if PE exited today
        
        # Check if CE position is still open
        if open_ce_position is not None:
            ce_exit_date_str = open_ce_position.get('exit_date')
            ce_exit_time_str = open_ce_position.get('exit_time')
            if ce_exit_date_str and ce_exit_time_str:
                try:
                    ce_exit_dt = datetime.strptime(f"{ce_exit_date_str} {ce_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                    if check_datetime < ce_exit_dt:
                        # Position is still open at check time
                        if ce_exit_date_str == date_str:
                            # Exit will happen today (after entry_time) - track it for re-entry logic
                            exit_reason = "EXPIRY"  # Default
                            # Try to find the trade in ce_trades to get exit reason
                            for trade in ce_trades:
                                if trade[2] == ce_exit_date_str and trade[3] == ce_exit_time_str:
                                    exit_reason = trade[4]  # exit_reason
                                    break
                            ce_exit_today = (ce_exit_time_str, exit_reason)
                            print(f"  CE position still open from {open_ce_position['entry_date']} {open_ce_position['entry_time']}, will exit on {ce_exit_date_str} {ce_exit_time_str} - blocking new CE entry")
                        else:
                            print(f"  CE position still open from {open_ce_position['entry_date']} {open_ce_position['entry_time']}, will exit on {ce_exit_date_str} {ce_exit_time_str} - blocking new CE entry")
                        trade_ce = False
                        ce_entry_time = None
                    else:
                        # Position has been closed, track it for re-entry
                        if ce_exit_date_str == date_str:
                            # Exit happened today - get exit reason from the trade if available
                            exit_reason = "EXPIRY"  # Default
                            # Try to find the trade in ce_trades to get exit reason
                            for trade in ce_trades:
                                if trade[2] == ce_exit_date_str and trade[3] == ce_exit_time_str:
                                    exit_reason = trade[4]  # exit_reason
                                    break
                            ce_exit_today = (ce_exit_time_str, exit_reason)
                        print(f"  CE position from {open_ce_position['entry_date']} {open_ce_position['entry_time']} was closed on {ce_exit_date_str} {ce_exit_time_str}")
                        open_ce_position = None
                except Exception as e:
                    # If parsing fails, clear the position
                    print(f"  Error checking CE position: {e}, clearing position")
                    open_ce_position = None
        
        # Check if PE position is still open
        if open_pe_position is not None:
            pe_exit_date_str = open_pe_position.get('exit_date')
            pe_exit_time_str = open_pe_position.get('exit_time')
            if pe_exit_date_str and pe_exit_time_str:
                try:
                    pe_exit_dt = datetime.strptime(f"{pe_exit_date_str} {pe_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                    if check_datetime < pe_exit_dt:
                        # Position is still open at check time
                        if pe_exit_date_str == date_str:
                            # Exit will happen today (after entry_time) - track it for re-entry logic
                            exit_reason = "EXPIRY"  # Default
                            # Try to find the trade in pe_trades to get exit reason
                            for trade in pe_trades:
                                if trade[2] == pe_exit_date_str and trade[3] == pe_exit_time_str:
                                    exit_reason = trade[4]  # exit_reason
                                    break
                            pe_exit_today = (pe_exit_time_str, exit_reason)
                            print(f"  PE position still open from {open_pe_position['entry_date']} {open_pe_position['entry_time']}, will exit on {pe_exit_date_str} {pe_exit_time_str} - blocking new PE entry")
                        else:
                            print(f"  PE position still open from {open_pe_position['entry_date']} {open_pe_position['entry_time']}, will exit on {pe_exit_date_str} {pe_exit_time_str} - blocking new PE entry")
                        trade_pe = False
                        pe_entry_time = None
                    else:
                        # Position has been closed, track it for re-entry
                        if pe_exit_date_str == date_str:
                            # Exit happened today - get exit reason from the trade if available
                            exit_reason = "EXPIRY"  # Default
                            # Try to find the trade in pe_trades to get exit reason
                            for trade in pe_trades:
                                if trade[2] == pe_exit_date_str and trade[3] == pe_exit_time_str:
                                    exit_reason = trade[4]  # exit_reason
                                    break
                            pe_exit_today = (pe_exit_time_str, exit_reason)
                        print(f"  PE position from {open_pe_position['entry_date']} {open_pe_position['entry_time']} was closed on {pe_exit_date_str} {pe_exit_time_str}")
                        open_pe_position = None
                except Exception as e:
                    # If parsing fails, clear the position
                    print(f"  Error checking PE position: {e}, clearing position")
                    open_pe_position = None
        
        # Apply no_existing_trades logic: if enabled, block ALL new trades (both legs) when ANY leg exists
        if no_existing_trades:
            # If CE position exists, block both CE and PE entry
            if open_ce_position is not None:
                ce_exit_date_str = open_ce_position.get('exit_date')
                ce_exit_time_str = open_ce_position.get('exit_time')
                if ce_exit_date_str and ce_exit_time_str:
                    try:
                        ce_exit_dt = datetime.strptime(f"{ce_exit_date_str} {ce_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                        if check_datetime < ce_exit_dt:
                            # CE position is still open, block both CE and PE entry
                            if trade_ce:
                                print(f"  No Existing Trades enabled: CE position exists from {open_ce_position['entry_date']} {open_ce_position['entry_time']}, blocking CE entry")
                                trade_ce = False
                                ce_entry_time = None
                            if trade_pe:
                                print(f"  No Existing Trades enabled: CE position exists from {open_ce_position['entry_date']} {open_ce_position['entry_time']}, blocking PE entry")
                                trade_pe = False
                                pe_entry_time = None
                    except:
                        pass  # If parsing fails, skip this check
            
            # If PE position exists, block both CE and PE entry
            if open_pe_position is not None:
                pe_exit_date_str = open_pe_position.get('exit_date')
                pe_exit_time_str = open_pe_position.get('exit_time')
                if pe_exit_date_str and pe_exit_time_str:
                    try:
                        pe_exit_dt = datetime.strptime(f"{pe_exit_date_str} {pe_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                        if check_datetime < pe_exit_dt:
                            # PE position is still open, block both CE and PE entry
                            if trade_ce:
                                print(f"  No Existing Trades enabled: PE position exists from {open_pe_position['entry_date']} {open_pe_position['entry_time']}, blocking CE entry")
                                trade_ce = False
                                ce_entry_time = None
                            if trade_pe:
                                print(f"  No Existing Trades enabled: PE position exists from {open_pe_position['entry_date']} {open_pe_position['entry_time']}, blocking PE entry")
                                trade_pe = False
                                pe_entry_time = None
                    except:
                        pass  # If parsing fails, skip this check
        
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
        expiry_date_str = options_data.get('expiry_date', None)
        expiry_date_dt = None
        if expiry_date_str:
            expiry_date_dt = parse_expiry_date(expiry_date_str)
            if expiry_date_dt is None:
                print(f"  Warning: Could not parse expiry_date '{expiry_date_str}', skipping trade")
                current_date += timedelta(days=1)
                continue
        
        # Get VIX at entry for record keeping (still using configured entry_time)
        vix_at_entry = None
        if vix_data is not None:
            vix_at_entry = get_vix_price_at_time(vix_data, date_str, entry_time)
        
        # POSITIONAL TRADING LOGIC: Exit on EMA exit, target hit, stop loss, or expiry
        # Priority: EMA exit > (First of: Target profit or Stop loss) > Expiry
        # Initialize exit variables
        ce_exit_date = None
        ce_exit_time = None
        pe_exit_date = None
        pe_exit_time = None
        ce_exit_reason = "EXPIRY"
        pe_exit_reason = "EXPIRY"
        ce_exit_price = None
        pe_exit_price = None
        ce_exit_nifty = None
        pe_exit_nifty = None
        ce_exit_fast_ema = None
        ce_exit_slow_ema = None
        pe_exit_fast_ema = None
        pe_exit_slow_ema = None
        
        # Get options data path
        options_data_path = config['data_paths']['options_data']
        
        # Check EMA exit for CE (positional - across multiple days until expiry)
        if ema_enabled and use_ema_exit and trade_ce and ce_entry_time and ce_strike is not None and expiry_date_dt:
            ce_ema_exit_date, ce_ema_exit_time, ce_ema_exit_nifty, ce_ema_exit_fast, ce_ema_exit_slow = check_ema_exit_condition_positional(
                nifty_data, date_str, ce_entry_time, expiry_date_dt, is_bullish=False, interval_minutes=ema_interval
            )
            if ce_ema_exit_date is not None:
                ce_exit_date = ce_ema_exit_date
                ce_exit_time = ce_ema_exit_time
                ce_exit_reason = "EMA_EXIT"
                ce_exit_nifty = ce_ema_exit_nifty
                ce_exit_fast_ema = ce_ema_exit_fast
                ce_exit_slow_ema = ce_ema_exit_slow
                # Get exit price at EMA exit time
                ce_exit_price = get_option_price_on_date(options_data_path, 'CE', ce_strike, ce_exit_date, ce_exit_time)
                if ce_exit_price is None:
                    # Try to get closest price
                    ce_exit_price = get_option_price_on_date(options_data_path, 'CE', ce_strike, ce_exit_date, "15:20:00")
                nifty_str = f", N: {ce_exit_nifty:.2f}" if ce_exit_nifty else ""
                print(f"    CE EMA Exit triggered on {ce_exit_date} at {ce_exit_time} - N:{ce_exit_nifty:.2f}, F:{ce_exit_fast_ema:.2f}, S:{ce_exit_slow_ema:.2f}, N>F, N>S{nifty_str}")
        
        # Check EMA exit for PE (positional - across multiple days until expiry)
        if ema_enabled and use_ema_exit and trade_pe and pe_entry_time and pe_strike is not None and expiry_date_dt:
            pe_ema_exit_date, pe_ema_exit_time, pe_ema_exit_nifty, pe_ema_exit_fast, pe_ema_exit_slow = check_ema_exit_condition_positional(
                nifty_data, date_str, pe_entry_time, expiry_date_dt, is_bullish=True, interval_minutes=ema_interval
            )
            if pe_ema_exit_date is not None:
                pe_exit_date = pe_ema_exit_date
                pe_exit_time = pe_ema_exit_time
                pe_exit_reason = "EMA_EXIT"
                pe_exit_nifty = pe_ema_exit_nifty
                pe_exit_fast_ema = pe_ema_exit_fast
                pe_exit_slow_ema = pe_ema_exit_slow
                # Get exit price at EMA exit time
                pe_exit_price = get_option_price_on_date(options_data_path, 'PE', pe_strike, pe_exit_date, pe_exit_time)
                if pe_exit_price is None:
                    # Try to get closest price
                    pe_exit_price = get_option_price_on_date(options_data_path, 'PE', pe_strike, pe_exit_date, "15:20:00")
                nifty_str = f", N: {pe_exit_nifty:.2f}" if pe_exit_nifty else ""
                print(f"    PE EMA Exit triggered on {pe_exit_date} at {pe_exit_time} - N:{pe_exit_nifty:.2f}, F:{pe_exit_fast_ema:.2f}, S:{pe_exit_slow_ema:.2f}, N<F, N<S{nifty_str}")
        
        # Check target profit and stop loss for CE (positional - across multiple days)
        # Check all exit conditions and use whichever happened first chronologically
        if trade_ce and ce_entry_time and ce_entry_price is not None and expiry_date_dt:
            ce_target_price = None
            ce_target_date = None
            ce_target_time = None
            ce_stop_loss_price = None
            ce_stop_loss_date = None
            ce_stop_loss_time = None
            
            # Check target profit if enabled (across multiple days until expiry)
            if target_percentage > 0:
                ce_target_price, ce_target_date, ce_target_time = check_target_profit_positional(
                    options_data_path, 'CE', ce_strike, date_str, ce_entry_time,
                    ce_entry_price, target_percentage, expiry_date_dt, use_next_expiry
                )
            
            # Check stop loss if enabled (across multiple days until expiry)
            if stop_loss_percentage > 0:
                ce_stop_loss_price, ce_stop_loss_date, ce_stop_loss_time = check_stop_loss_positional(
                    options_data_path, 'CE', ce_strike, date_str, ce_entry_time,
                    ce_entry_price, stop_loss_percentage, expiry_date_dt, use_next_expiry
                )
            
            # Determine which happened first: EMA exit, target profit, or stop loss
            exit_options = []
            
            # Add EMA exit if triggered
            if ce_exit_reason == "EMA_EXIT" and ce_exit_date and ce_exit_time:
                exit_options.append(("EMA_EXIT", ce_exit_date, ce_exit_time, ce_exit_price, ce_exit_nifty, ce_exit_fast_ema, ce_exit_slow_ema))
            
            # Add target profit if triggered
            if ce_target_date is not None:
                exit_options.append(("TARGET_HIT", ce_target_date, ce_target_time, ce_target_price, None, None, None))
            
            # Add stop loss if triggered
            if ce_stop_loss_date is not None:
                exit_options.append(("STOP_LOSS", ce_stop_loss_date, ce_stop_loss_time, ce_stop_loss_price, None, None, None))
            
            # Find the earliest exit
            if exit_options:
                # Sort by datetime to find earliest
                exit_options_with_dt = []
                for exit_type, exit_d, exit_t, exit_p, exit_n, exit_f, exit_s in exit_options:
                    try:
                        exit_dt = datetime.strptime(f"{exit_d} {exit_t}", "%Y-%m-%d %H:%M:%S")
                        exit_options_with_dt.append((exit_dt, exit_type, exit_d, exit_t, exit_p, exit_n, exit_f, exit_s))
                    except:
                        continue
                
                if exit_options_with_dt:
                    # Sort by datetime and get earliest
                    exit_options_with_dt.sort(key=lambda x: x[0])
                    earliest_dt, earliest_type, earliest_d, earliest_t, earliest_p, earliest_n, earliest_f, earliest_s = exit_options_with_dt[0]
                    
                    ce_exit_date = earliest_d
                    ce_exit_time = earliest_t
                    ce_exit_reason = earliest_type
                    ce_exit_price = earliest_p
                    if earliest_n is not None:
                        ce_exit_nifty = earliest_n
                    if earliest_f is not None:
                        ce_exit_fast_ema = earliest_f
                        ce_exit_slow_ema = earliest_s
                    
                    # Print appropriate message
                    if earliest_type == "EMA_EXIT":
                        nifty_str = f", N: {ce_exit_nifty:.2f}" if ce_exit_nifty else ""
                        print(f"    CE EMA Exit triggered on {ce_exit_date} at {ce_exit_time} - N:{ce_exit_nifty:.2f}, F:{ce_exit_fast_ema:.2f}, S:{ce_exit_slow_ema:.2f}, N>F, N>S{nifty_str}")
                    elif earliest_type == "TARGET_HIT":
                        ce_exit_nifty = get_nifty_price_at_time(nifty_data, ce_exit_date, ce_exit_time)
                        nifty_str = f", N: {ce_exit_nifty:.2f}" if ce_exit_nifty else ""
                        print(f"    CE Target Profit triggered on {ce_exit_date} at {ce_exit_time} - Entry: {ce_entry_price}, Exit: {ce_target_price} ({target_percentage}% profit{nifty_str})")
                    elif earliest_type == "STOP_LOSS":
                        ce_exit_nifty = get_nifty_price_at_time(nifty_data, ce_exit_date, ce_exit_time)
                        nifty_str = f", N: {ce_exit_nifty:.2f}" if ce_exit_nifty else ""
                        print(f"    CE Stop Loss triggered on {ce_exit_date} at {ce_exit_time} - Entry: {ce_entry_price}, Exit: {ce_stop_loss_price} ({stop_loss_percentage}% loss{nifty_str})")
            
            # If no exit triggered yet (no EMA exit, no target, no stop loss), exit on expiry
            if ce_exit_reason == "EXPIRY":
                # No target or stop loss hit - exit on expiry date
                ce_exit_date = expiry_date_dt.strftime("%Y-%m-%d")
                # Use last trading time (15:25:00) on expiry date
                ce_exit_time = exit_time
                ce_exit_reason = "EXPIRY"
                # Get exit price on expiry date
                ce_exit_price = get_option_price_on_date(options_data_path, 'CE', ce_strike, ce_exit_date, ce_exit_time)
                if ce_exit_price is None:
                    # Try to get closest price
                    ce_exit_price = get_option_price_on_date(options_data_path, 'CE', ce_strike, ce_exit_date, "15:20:00")
                ce_exit_nifty = get_nifty_price_at_time(nifty_data, ce_exit_date, ce_exit_time)
                nifty_str = f", N: {ce_exit_nifty:.2f}" if ce_exit_nifty else ""
                print(f"    CE Expired on {ce_exit_date} at {ce_exit_time} - Entry: {ce_entry_price}, Exit: {ce_exit_price}{nifty_str}")
        
        # Check target profit and stop loss for PE (positional - across multiple days)
        # Check all exit conditions and use whichever happened first chronologically
        if trade_pe and pe_entry_time and pe_entry_price is not None and expiry_date_dt:
            pe_target_price = None
            pe_target_date = None
            pe_target_time = None
            pe_stop_loss_price = None
            pe_stop_loss_date = None
            pe_stop_loss_time = None
            
            # Check target profit if enabled (across multiple days until expiry)
            if target_percentage > 0:
                pe_target_price, pe_target_date, pe_target_time = check_target_profit_positional(
                    options_data_path, 'PE', pe_strike, date_str, pe_entry_time,
                    pe_entry_price, target_percentage, expiry_date_dt, use_next_expiry
                )
            
            # Check stop loss if enabled (across multiple days until expiry)
            if stop_loss_percentage > 0:
                pe_stop_loss_price, pe_stop_loss_date, pe_stop_loss_time = check_stop_loss_positional(
                    options_data_path, 'PE', pe_strike, date_str, pe_entry_time,
                    pe_entry_price, stop_loss_percentage, expiry_date_dt, use_next_expiry
                )
            
            # Determine which happened first: EMA exit, target profit, or stop loss
            exit_options = []
            
            # Add EMA exit if triggered
            if pe_exit_reason == "EMA_EXIT" and pe_exit_date and pe_exit_time:
                exit_options.append(("EMA_EXIT", pe_exit_date, pe_exit_time, pe_exit_price, pe_exit_nifty, pe_exit_fast_ema, pe_exit_slow_ema))
            
            # Add target profit if triggered
            if pe_target_date is not None:
                exit_options.append(("TARGET_HIT", pe_target_date, pe_target_time, pe_target_price, None, None, None))
            
            # Add stop loss if triggered
            if pe_stop_loss_date is not None:
                exit_options.append(("STOP_LOSS", pe_stop_loss_date, pe_stop_loss_time, pe_stop_loss_price, None, None, None))
            
            # Find the earliest exit
            if exit_options:
                # Sort by datetime to find earliest
                exit_options_with_dt = []
                for exit_type, exit_d, exit_t, exit_p, exit_n, exit_f, exit_s in exit_options:
                    try:
                        exit_dt = datetime.strptime(f"{exit_d} {exit_t}", "%Y-%m-%d %H:%M:%S")
                        exit_options_with_dt.append((exit_dt, exit_type, exit_d, exit_t, exit_p, exit_n, exit_f, exit_s))
                    except:
                        continue
                
                if exit_options_with_dt:
                    # Sort by datetime and get earliest
                    exit_options_with_dt.sort(key=lambda x: x[0])
                    earliest_dt, earliest_type, earliest_d, earliest_t, earliest_p, earliest_n, earliest_f, earliest_s = exit_options_with_dt[0]
                    
                    pe_exit_date = earliest_d
                    pe_exit_time = earliest_t
                    pe_exit_reason = earliest_type
                    pe_exit_price = earliest_p
                    if earliest_n is not None:
                        pe_exit_nifty = earliest_n
                    if earliest_f is not None:
                        pe_exit_fast_ema = earliest_f
                        pe_exit_slow_ema = earliest_s
                    
                    # Print appropriate message
                    if earliest_type == "EMA_EXIT":
                        nifty_str = f", N: {pe_exit_nifty:.2f}" if pe_exit_nifty else ""
                        print(f"    PE EMA Exit triggered on {pe_exit_date} at {pe_exit_time} - N:{pe_exit_nifty:.2f}, F:{pe_exit_fast_ema:.2f}, S:{pe_exit_slow_ema:.2f}, N<F, N<S{nifty_str}")
                    elif earliest_type == "TARGET_HIT":
                        pe_exit_nifty = get_nifty_price_at_time(nifty_data, pe_exit_date, pe_exit_time)
                        nifty_str = f", N: {pe_exit_nifty:.2f}" if pe_exit_nifty else ""
                        print(f"    PE Target Profit triggered on {pe_exit_date} at {pe_exit_time} - Entry: {pe_entry_price}, Exit: {pe_target_price} ({target_percentage}% profit{nifty_str})")
                    elif earliest_type == "STOP_LOSS":
                        pe_exit_nifty = get_nifty_price_at_time(nifty_data, pe_exit_date, pe_exit_time)
                        nifty_str = f", N: {pe_exit_nifty:.2f}" if pe_exit_nifty else ""
                        print(f"    PE Stop Loss triggered on {pe_exit_date} at {pe_exit_time} - Entry: {pe_entry_price}, Exit: {pe_stop_loss_price} ({stop_loss_percentage}% loss{nifty_str})")
            
            # If no exit triggered yet (no EMA exit, no target, no stop loss), exit on expiry
            if pe_exit_reason == "EXPIRY":
                # No target or stop loss hit - exit on expiry date
                pe_exit_date = expiry_date_dt.strftime("%Y-%m-%d")
                # Use last trading time (15:25:00) on expiry date
                pe_exit_time = exit_time
                pe_exit_reason = "EXPIRY"
                # Get exit price on expiry date
                pe_exit_price = get_option_price_on_date(options_data_path, 'PE', pe_strike, pe_exit_date, pe_exit_time)
                if pe_exit_price is None:
                    # Try to get closest price
                    pe_exit_price = get_option_price_on_date(options_data_path, 'PE', pe_strike, pe_exit_date, "15:20:00")
                pe_exit_nifty = get_nifty_price_at_time(nifty_data, pe_exit_date, pe_exit_time)
                nifty_str = f", N: {pe_exit_nifty:.2f}" if pe_exit_nifty else ""
                print(f"    PE Expired on {pe_exit_date} at {pe_exit_time} - Entry: {pe_entry_price}, Exit: {pe_exit_price}{nifty_str}")
        
        # Get EMA values at actual exit times (for positional, exit may be on different date)
        # Use pre-calculated values from EMA exit if available, otherwise fetch them
        if ema_enabled:
            if ce_exit_reason == "EMA_EXIT" and ce_exit_fast_ema is not None:
                fast_ema_exit_ce = ce_exit_fast_ema
                slow_ema_exit_ce = ce_exit_slow_ema
            elif ce_exit_date and ce_exit_time:
                fast_ema_exit_ce, slow_ema_exit_ce = get_ema_from_nifty_data(nifty_data, ce_exit_date, ce_exit_time)
            else:
                fast_ema_exit_ce, slow_ema_exit_ce = None, None
            
            if pe_exit_reason == "EMA_EXIT" and pe_exit_fast_ema is not None:
                fast_ema_exit_pe = pe_exit_fast_ema
                slow_ema_exit_pe = pe_exit_slow_ema
            elif pe_exit_date and pe_exit_time:
                fast_ema_exit_pe, slow_ema_exit_pe = get_ema_from_nifty_data(nifty_data, pe_exit_date, pe_exit_time)
            else:
                fast_ema_exit_pe, slow_ema_exit_pe = None, None
        else:
            fast_ema_exit_ce = None
            slow_ema_exit_ce = None
            fast_ema_exit_pe = None
            slow_ema_exit_pe = None
        
        # Store all trades (initial + re-entries) for each leg
        ce_trades = []  # List of (entry_price, exit_price, exit_date, exit_time, exit_reason, strike, entry_time, entry_date)
        pe_trades = []  # List of (entry_price, exit_price, exit_date, exit_time, exit_reason, strike, entry_time, entry_date)
        
        # Track if we had initial trades on this day
        initial_ce_traded = False
        initial_pe_traded = False
        
        # Process CE leg - initial positional trade
        if trade_ce and ce_entry_price is not None and ce_strike is not None:
            # If exit price is None, use entry price as fallback (trade still occurred)
            final_ce_exit_price = ce_exit_price if ce_exit_price is not None else ce_entry_price
            # Store the positional trade
            ce_trades.append((ce_entry_price, final_ce_exit_price, ce_exit_date, ce_exit_time, ce_exit_reason, ce_strike, ce_entry_time, date_str))
            initial_ce_traded = True
            # Track open CE position only if exit is in the future (not today)
            if ce_exit_date and ce_exit_time:
                try:
                    exit_date_dt = datetime.strptime(ce_exit_date, "%Y-%m-%d")
                    # Only set open position if exit is in the future
                    if exit_date_dt > current_date:
                        open_ce_position = {
                            "entry_date": date_str,
                            "entry_time": ce_entry_time,
                            "exit_date": ce_exit_date,
                            "exit_time": ce_exit_time,
                            "exit_reason": ce_exit_reason,  # Store exit reason for cooldown calculation
                            "strike": ce_strike,
                            "expiry_date": expiry_date_dt
                        }
                    else:
                        # Exit is today or in the past, position is closed
                        open_ce_position = None
                except:
                    # If parsing fails, don't set open position
                    open_ce_position = None

        # Process PE leg - initial positional trade
        if trade_pe and pe_entry_price is not None and pe_strike is not None:
            # If exit price is None, use entry price as fallback (trade still occurred)
            final_pe_exit_price = pe_exit_price if pe_exit_price is not None else pe_entry_price
            # Store the positional trade
            pe_trades.append((pe_entry_price, final_pe_exit_price, pe_exit_date, pe_exit_time, pe_exit_reason, pe_strike, pe_entry_time, date_str))
            initial_pe_traded = True
            # Track open PE position only if exit is in the future (not today)
            if pe_exit_date and pe_exit_time:
                try:
                    exit_date_dt = datetime.strptime(pe_exit_date, "%Y-%m-%d")
                    # Only set open position if exit is in the future
                    if exit_date_dt > current_date:
                        open_pe_position = {
                            "entry_date": date_str,
                            "entry_time": pe_entry_time,
                            "exit_date": pe_exit_date,
                            "exit_time": pe_exit_time,
                            "exit_reason": pe_exit_reason,  # Store exit reason for cooldown calculation
                            "strike": pe_strike,
                            "expiry_date": expiry_date_dt
                        }
                    else:
                        # Exit is today or in the past, position is closed
                        open_pe_position = None
                except:
                    # If parsing fails, don't set open position
                    open_pe_position = None
        
        # RE-ENTRY LOGIC FOR POSITIONAL TRADES
        # Allow multiple re-entries per day up to max_reentries, while
        # preserving existing EMA/VIX/SL/TP/cooldown logic.
        if reentry_enabled and max_reentries > 0:
            # Track if we've already processed re-entry for exits that happen during the day
            reentry_processed_for_day = False
            
            while True:
                # Re-check open positions to see if any exited during the day
                # This handles cases where positions exit after entry_time
                current_ce_exit_today = ce_exit_today
                current_pe_exit_today = pe_exit_today
                
                # Check if CE position exits today (even if exit time is after entry_time)
                if open_ce_position is not None:
                    ce_exit_date_str = open_ce_position.get('exit_date')
                    ce_exit_time_str = open_ce_position.get('exit_time')
                    if ce_exit_date_str == date_str and ce_exit_time_str:
                        # Position exits today - track it
                        # First try to get exit_reason from open_ce_position (stored when position was created)
                        exit_reason = open_ce_position.get('exit_reason', "EXPIRY")
                        # Fallback: Try to find the trade in ce_trades to get exit reason
                        if exit_reason == "EXPIRY":
                            for trade in ce_trades:
                                if trade[2] == ce_exit_date_str and trade[3] == ce_exit_time_str:
                                    exit_reason = trade[4]  # exit_reason
                                    break
                        # If still not found, use the exit reason from ce_exit_today if available
                        if exit_reason == "EXPIRY" and ce_exit_today and ce_exit_today[0] == ce_exit_time_str:
                            exit_reason = ce_exit_today[1]
                        current_ce_exit_today = (ce_exit_time_str, exit_reason)
                
                # Check if PE position exits today (even if exit time is after entry_time)
                if open_pe_position is not None:
                    pe_exit_date_str = open_pe_position.get('exit_date')
                    pe_exit_time_str = open_pe_position.get('exit_time')
                    if pe_exit_date_str == date_str and pe_exit_time_str:
                        # Position exits today - track it
                        # First try to get exit_reason from open_pe_position (stored when position was created)
                        exit_reason = open_pe_position.get('exit_reason', "EXPIRY")
                        # Fallback: Try to find the trade in pe_trades to get exit reason
                        if exit_reason == "EXPIRY":
                            for trade in pe_trades:
                                if trade[2] == pe_exit_date_str and trade[3] == pe_exit_time_str:
                                    exit_reason = trade[4]  # exit_reason
                                    break
                        # If still not found, use the exit reason from pe_exit_today if available
                        if exit_reason == "EXPIRY" and pe_exit_today and pe_exit_today[0] == pe_exit_time_str:
                            exit_reason = pe_exit_today[1]
                        current_pe_exit_today = (pe_exit_time_str, exit_reason)
                        
                        # Check if the exit time has passed - if so, clear the open position for re-entry purposes
                        try:
                            pe_exit_dt = datetime.strptime(f"{pe_exit_date_str} {pe_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                            # Use the common re-entry time if available, otherwise use entry_time
                            if 'common_reentry_time' in locals() and common_reentry_time:
                                reentry_check_dt = datetime.strptime(f"{date_str} {common_reentry_time}", "%Y-%m-%d %H:%M:%S")
                            else:
                                reentry_check_dt = datetime.strptime(f"{date_str} {entry_time}", "%Y-%m-%d %H:%M:%S")
                            
                            # If exit time has passed, treat position as closed for re-entry
                            if reentry_check_dt >= pe_exit_dt:
                                # Position has exited, don't block re-entry
                                pass
                            else:
                                # Position hasn't exited yet at re-entry time, block re-entry if no_existing_trades
                                if no_existing_trades:
                                    break
                        except:
                            pass
                
                # Re-entry can only happen if both open positions are None (both legs closed)
                # Also consider positions closed if they exit today (even if still marked as open at entry_time)
                ce_closed = (open_ce_position is None) or (current_ce_exit_today is not None)
                pe_closed = (open_pe_position is None) or (current_pe_exit_today is not None)
                both_legs_closed = (ce_closed and pe_closed)

                # Determine if there have been any trades entered today
                ce_trades_today = [t for t in ce_trades if t[7] == date_str]
                pe_trades_today = [t for t in pe_trades if t[7] == date_str]
                had_trades_today = bool(ce_trades_today or pe_trades_today)

                # Find the latest CE trade that exited today (could be from today or previous day entry)
                last_ce_exit_today = None
                for trade in reversed(ce_trades):
                    if trade[2] == date_str:  # exit_date is today
                        last_ce_exit_today = trade
                        break
                
                # Find the latest PE trade that exited today (could be from today or previous day entry)
                last_pe_exit_today = None
                for trade in reversed(pe_trades):
                    if trade[2] == date_str:  # exit_date is today
                        last_pe_exit_today = trade
                        break
                
                # Check if any trades exited today (either entered today or from previous days)
                any_exit_today = (last_ce_exit_today is not None) or (last_pe_exit_today is not None) or (current_ce_exit_today is not None) or (current_pe_exit_today is not None)

                # Re-entry is allowed if:
                # 1. Both legs are closed (no open positions), AND
                # 2. Either: (a) any trades exited today (same-day or cross-day re-entry), OR
                #            (b) there have been no trades entered today (allows re-entry on days
                #                after previous positions have been fully exited)
                if not (both_legs_closed and (any_exit_today or not had_trades_today)):
                    break

                # Determine the earliest re-entry time for each leg independently
                # Each leg should have its own cooldown based on its own exit reason
                earliest_ce_reentry_time = None
                earliest_pe_reentry_time = None

                if any_exit_today:
                    # Find CE exit time and reason
                    ce_exit_dt = None
                    ce_exit_reason = None
                    
                    # Prioritize current_ce_exit_today (from open position) over last_ce_exit_today (from trades)
                    # This handles cases where positions exit during the day
                    if current_ce_exit_today:
                        exit_time_str, exit_reason = current_ce_exit_today
                        ce_exit_dt = datetime.strptime(f"{date_str} {exit_time_str}", "%Y-%m-%d %H:%M:%S")
                        ce_exit_reason = exit_reason
                    elif last_ce_exit_today and last_ce_exit_today[3]:
                        ce_exit_dt = datetime.strptime(f"{date_str} {last_ce_exit_today[3]}", "%Y-%m-%d %H:%M:%S")
                        ce_exit_reason = last_ce_exit_today[4]
                    
                    # Find PE exit time and reason
                    pe_exit_dt = None
                    pe_exit_reason = None
                    
                    # Prioritize current_pe_exit_today (from open position) over last_pe_exit_today (from trades)
                    # This handles cases where positions exit during the day
                    if current_pe_exit_today:
                        exit_time_str, exit_reason = current_pe_exit_today
                        pe_exit_dt = datetime.strptime(f"{date_str} {exit_time_str}", "%Y-%m-%d %H:%M:%S")
                        pe_exit_reason = exit_reason
                    elif last_pe_exit_today and last_pe_exit_today[3]:
                        pe_exit_dt = datetime.strptime(f"{date_str} {last_pe_exit_today[3]}", "%Y-%m-%d %H:%M:%S")
                        pe_exit_reason = last_pe_exit_today[4]
                    
                    # Calculate CE re-entry time with cooldown if needed
                    if ce_exit_dt:
                        earliest_ce_reentry_time = ce_exit_dt.strftime("%H:%M:%S")
                        # Apply cooldown if CE exit was due to stop loss
                        if ce_exit_reason == "STOP_LOSS" and stop_loss_cooldown_minutes > 0:
                            cooldown_end_dt = ce_exit_dt + timedelta(minutes=stop_loss_cooldown_minutes)
                            earliest_ce_reentry_time = cooldown_end_dt.strftime("%H:%M:%S")
                    else:
                        earliest_ce_reentry_time = entry_time
                    
                    # Calculate PE re-entry time with cooldown if needed
                    if pe_exit_dt:
                        earliest_pe_reentry_time = pe_exit_dt.strftime("%H:%M:%S")
                        # Apply cooldown if PE exit was due to stop loss
                        if pe_exit_reason == "STOP_LOSS" and stop_loss_cooldown_minutes > 0:
                            cooldown_end_dt = pe_exit_dt + timedelta(minutes=stop_loss_cooldown_minutes)
                            earliest_pe_reentry_time = cooldown_end_dt.strftime("%H:%M:%S")
                    else:
                        earliest_pe_reentry_time = entry_time
                    
                    # Use the later of the two times as the overall earliest time (both legs must be ready)
                    # If only one leg exited, use its re-entry time (the other leg can enter at the same time)
                    reentry_times = []
                    if earliest_ce_reentry_time:
                        reentry_times.append(earliest_ce_reentry_time)
                    if earliest_pe_reentry_time:
                        reentry_times.append(earliest_pe_reentry_time)
                    
                    if reentry_times:
                        reentry_dts = [datetime.strptime(f"{date_str} {t}", "%Y-%m-%d %H:%M:%S") for t in reentry_times]
                        latest_reentry_dt = max(reentry_dts)
                        earliest_reentry_time = latest_reentry_dt.strftime("%H:%M:%S")
                        # If one leg didn't exit, set its re-entry time to match the other leg's time
                        if not earliest_ce_reentry_time:
                            earliest_ce_reentry_time = earliest_reentry_time
                        if not earliest_pe_reentry_time:
                            earliest_pe_reentry_time = earliest_reentry_time
                    else:
                        earliest_reentry_time = entry_time
                        earliest_ce_reentry_time = entry_time
                        earliest_pe_reentry_time = entry_time
                else:
                    # No trades today, both legs closed from previous days - can re-enter at entry_time
                    earliest_ce_reentry_time = entry_time
                    earliest_pe_reentry_time = entry_time
                    earliest_reentry_time = entry_time

                # Check if re-entry is allowed based on time cutoff
                if not (earliest_reentry_time and is_reentry_allowed(earliest_reentry_time, no_reentry_after)):
                    break

                # Count existing re-entries (trades after the first one)
                ce_reentry_count = len(ce_trades) - (1 if initial_ce_traded else 0)
                pe_reentry_count = len(pe_trades) - (1 if initial_pe_traded else 0)
                total_reentries = max(ce_reentry_count, pe_reentry_count)

                if total_reentries >= max_reentries:
                    break

                # Look for re-entry opportunities
                search_end_time = exit_time
                if no_reentry_after:
                    search_end_dt = datetime.strptime(f"{date_str} {no_reentry_after}", "%Y-%m-%d %H:%M:%S")
                    exit_dt = datetime.strptime(f"{date_str} {exit_time}", "%Y-%m-%d %H:%M:%S")
                    if search_end_dt < exit_dt:
                        search_end_time = no_reentry_after

                # Both legs must enter simultaneously after both cooldowns complete
                # Use the maximum of both earliest re-entry times as the common entry time
                common_reentry_time = earliest_reentry_time
                
                # Find EMA-based re-entry times if enabled
                reentry_ce_time = None
                reentry_pe_time = None

                if reentry_based_on_ema_signals or ema_enabled:
                    # For EMA-based re-entry, find signals starting from the common re-entry time
                    reentry_ce_time, reentry_pe_time, _, _ = find_ema_entry_times(
                        nifty_data,
                        date_str,
                        common_reentry_time,
                        search_end_time,
                        ema_interval,
                        None,
                        round_to_ema_interval,
                        use_ema_cross_entry,
                    )
                    
                    # Ensure re-entry times are at or after the common time (both legs enter together)
                    if reentry_ce_time:
                        reentry_ce_dt = datetime.strptime(f"{date_str} {reentry_ce_time}", "%Y-%m-%d %H:%M:%S")
                        common_dt = datetime.strptime(f"{date_str} {common_reentry_time}", "%Y-%m-%d %H:%M:%S")
                        if reentry_ce_dt < common_dt:
                            reentry_ce_time = common_reentry_time
                    
                    if reentry_pe_time:
                        reentry_pe_dt = datetime.strptime(f"{date_str} {reentry_pe_time}", "%Y-%m-%d %H:%M:%S")
                        common_dt = datetime.strptime(f"{date_str} {common_reentry_time}", "%Y-%m-%d %H:%M:%S")
                        if reentry_pe_dt < common_dt:
                            reentry_pe_time = common_reentry_time
                else:
                    # When EMA is disabled, both legs enter simultaneously at the common re-entry time
                    exit_dt = datetime.strptime(f"{date_str} {exit_time}", "%Y-%m-%d %H:%M:%S")
                    common_dt = datetime.strptime(f"{date_str} {common_reentry_time}", "%Y-%m-%d %H:%M:%S")
                    if common_dt < exit_dt:
                        reentry_ce_time = common_reentry_time
                        reentry_pe_time = common_reentry_time

                # Both legs must enter together - only proceed if both have valid re-entry times
                # and no existing positions exist
                if not (reentry_ce_time and reentry_pe_time):
                    break
                
                if not is_reentry_allowed(reentry_ce_time, no_reentry_after) or not is_reentry_allowed(reentry_pe_time, no_reentry_after):
                    break
                
                # Check that no existing positions exist before allowing re-entry
                # Exception: if a position exits today, it's considered closed for re-entry purposes (after cooldown)
                # With no_existing_trades enabled, block re-entry if ANY position exists AND doesn't exit today
                # Also check if position exits today but AFTER the re-entry time - if so, block re-entry
                if no_existing_trades:
                    # Check if any position exists and will still be open at re-entry time
                    reentry_check_dt = datetime.strptime(f"{date_str} {common_reentry_time}", "%Y-%m-%d %H:%M:%S")
                    
                    if open_ce_position is not None:
                        ce_exit_date_str = open_ce_position.get('exit_date')
                        ce_exit_time_str = open_ce_position.get('exit_time')
                        if ce_exit_date_str and ce_exit_time_str:
                            try:
                                ce_exit_dt = datetime.strptime(f"{ce_exit_date_str} {ce_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                                # Block if position is still open at re-entry time (even if it exits today)
                                if reentry_check_dt < ce_exit_dt:
                                    break
                            except:
                                # If parsing fails, block to be safe
                                break
                    
                    if open_pe_position is not None:
                        pe_exit_date_str = open_pe_position.get('exit_date')
                        pe_exit_time_str = open_pe_position.get('exit_time')
                        if pe_exit_date_str and pe_exit_time_str:
                            try:
                                pe_exit_dt = datetime.strptime(f"{pe_exit_date_str} {pe_exit_time_str}", "%Y-%m-%d %H:%M:%S")
                                # Block if position is still open at re-entry time (even if it exits today)
                                if reentry_check_dt < pe_exit_dt:
                                    break
                            except:
                                # If parsing fails, block to be safe
                                break
                else:
                    # Without no_existing_trades, only block if position exists and doesn't exit today
                    ce_blocking = (open_ce_position is not None) and (current_ce_exit_today is None)
                    pe_blocking = (open_pe_position is not None) and (current_pe_exit_today is None)
                    if ce_blocking or pe_blocking:
                        break

                # Process CE re-entry
                if ce_reentry_count < max_reentries:
                    # Check VIX EMA signal if enabled
                    vix_ema_blocked = False
                    if vix_ema_signal and vix_data is not None:
                        vix_check_time = reentry_ce_time
                        if round_to_ema_interval:
                            vix_check_time = round_time_to_interval(reentry_ce_time, ema_interval)
                        vix_reentry_price = get_vix_price_at_time(vix_data, date_str, vix_check_time)
                        vix_reentry_base_ema = get_vix_base_ema_at_time(vix_data, date_str, vix_check_time)
                        if (
                            vix_reentry_price is not None
                            and vix_reentry_base_ema is not None
                            and vix_reentry_price > vix_reentry_base_ema
                        ):
                            vix_ema_blocked = True

                    if not vix_ema_blocked:
                        # Get new strike and entry price for re-entry
                        reentry_nifty = (
                            get_nifty_price_at_time(nifty_data, date_str, reentry_ce_time) or nifty_entry_price
                        )
                        new_ce_strike = find_atm_strike(reentry_nifty, strike_rounding) + (
                            ce_offset * strike_rounding
                        )
                        new_ce_entry_price = get_option_price_closest(
                            options_data, "CE", new_ce_strike, reentry_ce_time
                        )

                        if new_ce_entry_price is not None:
                            # Calculate exit for re-entry (same logic as initial trade)
                            reentry_ce_exit_date = None
                            reentry_ce_exit_time = None
                            reentry_ce_exit_reason = "EXPIRY"
                            reentry_ce_exit_price = None

                            # Check EMA exit for re-entry CE
                            if ema_enabled and use_ema_exit and expiry_date_dt:
                                (
                                    reentry_ce_ema_exit_date,
                                    reentry_ce_ema_exit_time,
                                    _,
                                    _,
                                    _,
                                ) = check_ema_exit_condition_positional(
                                    nifty_data,
                                    date_str,
                                    reentry_ce_time,
                                    expiry_date_dt,
                                    is_bullish=False,
                                    interval_minutes=ema_interval,
                                )
                                if reentry_ce_ema_exit_date is not None:
                                    reentry_ce_exit_date = reentry_ce_ema_exit_date
                                    reentry_ce_exit_time = reentry_ce_ema_exit_time
                                    reentry_ce_exit_reason = "EMA_EXIT"
                                    reentry_ce_exit_price = get_option_price_on_date(
                                        options_data_path,
                                        "CE",
                                        new_ce_strike,
                                        reentry_ce_exit_date,
                                        reentry_ce_exit_time,
                                    )

                            # Check target and stop loss for re-entry CE
                            if reentry_ce_exit_reason != "EMA_EXIT":
                                reentry_ce_target_price = None
                                reentry_ce_target_date = None
                                reentry_ce_target_time = None
                                reentry_ce_stop_loss_price = None
                                reentry_ce_stop_loss_date = None
                                reentry_ce_stop_loss_time = None

                                if target_percentage > 0:
                                    (
                                        reentry_ce_target_price,
                                        reentry_ce_target_date,
                                        reentry_ce_target_time,
                                    ) = check_target_profit_positional(
                                        options_data_path,
                                        "CE",
                                        new_ce_strike,
                                        date_str,
                                        reentry_ce_time,
                                        new_ce_entry_price,
                                        target_percentage,
                                        expiry_date_dt,
                                        use_next_expiry,
                                    )

                                if stop_loss_percentage > 0:
                                    (
                                        reentry_ce_stop_loss_price,
                                        reentry_ce_stop_loss_date,
                                        reentry_ce_stop_loss_time,
                                    ) = check_stop_loss_positional(
                                        options_data_path,
                                        "CE",
                                        new_ce_strike,
                                        date_str,
                                        reentry_ce_time,
                                        new_ce_entry_price,
                                        stop_loss_percentage,
                                        expiry_date_dt,
                                        use_next_expiry,
                                    )

                                # Find earliest exit
                                exit_options = []
                                if reentry_ce_target_date:
                                    exit_options.append(
                                        (
                                            "TARGET_HIT",
                                            reentry_ce_target_date,
                                            reentry_ce_target_time,
                                            reentry_ce_target_price,
                                        )
                                    )
                                if reentry_ce_stop_loss_date:
                                    exit_options.append(
                                        (
                                            "STOP_LOSS",
                                            reentry_ce_stop_loss_date,
                                            reentry_ce_stop_loss_time,
                                            reentry_ce_stop_loss_price,
                                        )
                                    )

                                if exit_options:
                                    exit_options_with_dt = []
                                    for exit_type, exit_d, exit_t, exit_p in exit_options:
                                        try:
                                            exit_dt = datetime.strptime(
                                                f"{exit_d} {exit_t}", "%Y-%m-%d %H:%M:%S"
                                            )
                                            exit_options_with_dt.append(
                                                (exit_dt, exit_type, exit_d, exit_t, exit_p)
                                            )
                                        except:
                                            continue

                                    if exit_options_with_dt:
                                        exit_options_with_dt.sort(key=lambda x: x[0])
                                        (
                                            _,
                                            earliest_type,
                                            earliest_d,
                                            earliest_t,
                                            earliest_p,
                                        ) = exit_options_with_dt[0]
                                        reentry_ce_exit_date = earliest_d
                                        reentry_ce_exit_time = earliest_t
                                        reentry_ce_exit_reason = earliest_type
                                        reentry_ce_exit_price = earliest_p

                            # If no exit triggered, use expiry
                            if reentry_ce_exit_reason == "EXPIRY":
                                reentry_ce_exit_date = expiry_date_dt.strftime("%Y-%m-%d")
                                reentry_ce_exit_time = exit_time
                                reentry_ce_exit_price = get_option_price_on_date(
                                    options_data_path,
                                    "CE",
                                    new_ce_strike,
                                    reentry_ce_exit_date,
                                    reentry_ce_exit_time,
                                )

                            # Store re-entry trade
                            final_reentry_ce_exit_price = (
                                reentry_ce_exit_price
                                if reentry_ce_exit_price is not None
                                else new_ce_entry_price
                            )
                            ce_trades.append(
                                (
                                    new_ce_entry_price,
                                    final_reentry_ce_exit_price,
                                    reentry_ce_exit_date,
                                    reentry_ce_exit_time,
                                    reentry_ce_exit_reason,
                                    new_ce_strike,
                                    reentry_ce_time,
                                    date_str,
                                )
                            )

                            # Update open position only if exit is in the future (not today)
                            if reentry_ce_exit_date and reentry_ce_exit_time:
                                try:
                                    reentry_ce_exit_date_dt = datetime.strptime(
                                        reentry_ce_exit_date, "%Y-%m-%d"
                                    )
                                    if reentry_ce_exit_date_dt > current_date:
                                        open_ce_position = {
                                            "entry_date": date_str,
                                            "entry_time": reentry_ce_time,
                                            "exit_date": reentry_ce_exit_date,
                                            "exit_time": reentry_ce_exit_time,
                                            "exit_reason": reentry_ce_exit_reason,  # Store exit reason for cooldown calculation
                                            "strike": new_ce_strike,
                                            "expiry_date": expiry_date_dt,
                                        }
                                    else:
                                        open_ce_position = None
                                except:
                                    open_ce_position = None

                            ce_reentry_count += 1
                            print(
                                f"  CE Re-entry #{ce_reentry_count} at {reentry_ce_time} @ {new_ce_entry_price} (Strike: {new_ce_strike})"
                            )

                # Process PE re-entry (both legs enter together)
                if pe_reentry_count < max_reentries:
                    # Check VIX EMA signal if enabled
                    vix_ema_blocked = False
                    if vix_ema_signal and vix_data is not None:
                        vix_check_time = reentry_pe_time
                        if round_to_ema_interval:
                            vix_check_time = round_time_to_interval(reentry_pe_time, ema_interval)
                        vix_reentry_price = get_vix_price_at_time(vix_data, date_str, vix_check_time)
                        vix_reentry_base_ema = get_vix_base_ema_at_time(vix_data, date_str, vix_check_time)
                        if (
                            vix_reentry_price is not None
                            and vix_reentry_base_ema is not None
                            and vix_reentry_price > vix_reentry_base_ema
                        ):
                            vix_ema_blocked = True

                    if not vix_ema_blocked:
                        # Get new strike and entry price for re-entry
                        reentry_nifty = (
                            get_nifty_price_at_time(nifty_data, date_str, reentry_pe_time) or nifty_entry_price
                        )
                        new_pe_strike = find_atm_strike(reentry_nifty, strike_rounding) + (
                            pe_offset * strike_rounding
                        )
                        new_pe_entry_price = get_option_price_closest(
                            options_data, "PE", new_pe_strike, reentry_pe_time
                        )

                        if new_pe_entry_price is not None:
                            # Calculate exit for re-entry (same logic as initial trade)
                            reentry_pe_exit_date = None
                            reentry_pe_exit_time = None
                            reentry_pe_exit_reason = "EXPIRY"
                            reentry_pe_exit_price = None

                            # Check EMA exit for re-entry PE
                            if ema_enabled and use_ema_exit and expiry_date_dt:
                                (
                                    reentry_pe_ema_exit_date,
                                    reentry_pe_ema_exit_time,
                                    _,
                                    _,
                                    _,
                                ) = check_ema_exit_condition_positional(
                                    nifty_data,
                                    date_str,
                                    reentry_pe_time,
                                    expiry_date_dt,
                                    is_bullish=True,
                                    interval_minutes=ema_interval,
                                )
                                if reentry_pe_ema_exit_date is not None:
                                    reentry_pe_exit_date = reentry_pe_ema_exit_date
                                    reentry_pe_exit_time = reentry_pe_ema_exit_time
                                    reentry_pe_exit_reason = "EMA_EXIT"
                                    reentry_pe_exit_price = get_option_price_on_date(
                                        options_data_path,
                                        "PE",
                                        new_pe_strike,
                                        reentry_pe_exit_date,
                                        reentry_pe_exit_time,
                                    )

                            # Check target and stop loss for re-entry PE
                            if reentry_pe_exit_reason != "EMA_EXIT":
                                reentry_pe_target_price = None
                                reentry_pe_target_date = None
                                reentry_pe_target_time = None
                                reentry_pe_stop_loss_price = None
                                reentry_pe_stop_loss_date = None
                                reentry_pe_stop_loss_time = None

                                if target_percentage > 0:
                                    (
                                        reentry_pe_target_price,
                                        reentry_pe_target_date,
                                        reentry_pe_target_time,
                                    ) = check_target_profit_positional(
                                        options_data_path,
                                        "PE",
                                        new_pe_strike,
                                        date_str,
                                        reentry_pe_time,
                                        new_pe_entry_price,
                                        target_percentage,
                                        expiry_date_dt,
                                        use_next_expiry,
                                    )

                                if stop_loss_percentage > 0:
                                    (
                                        reentry_pe_stop_loss_price,
                                        reentry_pe_stop_loss_date,
                                        reentry_pe_stop_loss_time,
                                    ) = check_stop_loss_positional(
                                        options_data_path,
                                        "PE",
                                        new_pe_strike,
                                        date_str,
                                        reentry_pe_time,
                                        new_pe_entry_price,
                                        stop_loss_percentage,
                                        expiry_date_dt,
                                        use_next_expiry,
                                    )

                                # Find earliest exit
                                exit_options = []
                                if reentry_pe_target_date:
                                    exit_options.append(
                                        (
                                            "TARGET_HIT",
                                            reentry_pe_target_date,
                                            reentry_pe_target_time,
                                            reentry_pe_target_price,
                                        )
                                    )
                                if reentry_pe_stop_loss_date:
                                    exit_options.append(
                                        (
                                            "STOP_LOSS",
                                            reentry_pe_stop_loss_date,
                                            reentry_pe_stop_loss_time,
                                            reentry_pe_stop_loss_price,
                                        )
                                    )

                                if exit_options:
                                    exit_options_with_dt = []
                                    for exit_type, exit_d, exit_t, exit_p in exit_options:
                                        try:
                                            exit_dt = datetime.strptime(
                                                f"{exit_d} {exit_t}", "%Y-%m-%d %H:%M:%S"
                                            )
                                            exit_options_with_dt.append(
                                                (exit_dt, exit_type, exit_d, exit_t, exit_p)
                                            )
                                        except:
                                            continue

                                    if exit_options_with_dt:
                                        exit_options_with_dt.sort(key=lambda x: x[0])
                                        (
                                            _,
                                            earliest_type,
                                            earliest_d,
                                            earliest_t,
                                            earliest_p,
                                        ) = exit_options_with_dt[0]
                                        reentry_pe_exit_date = earliest_d
                                        reentry_pe_exit_time = earliest_t
                                        reentry_pe_exit_reason = earliest_type
                                        reentry_pe_exit_price = earliest_p

                            # If no exit triggered, use expiry
                            if reentry_pe_exit_reason == "EXPIRY":
                                reentry_pe_exit_date = expiry_date_dt.strftime("%Y-%m-%d")
                                reentry_pe_exit_time = exit_time
                                reentry_pe_exit_price = get_option_price_on_date(
                                    options_data_path,
                                    "PE",
                                    new_pe_strike,
                                    reentry_pe_exit_date,
                                    reentry_pe_exit_time,
                                )

                            # Store re-entry trade
                            final_reentry_pe_exit_price = (
                                reentry_pe_exit_price
                                if reentry_pe_exit_price is not None
                                else new_pe_entry_price
                            )
                            pe_trades.append(
                                (
                                    new_pe_entry_price,
                                    final_reentry_pe_exit_price,
                                    reentry_pe_exit_date,
                                    reentry_pe_exit_time,
                                    reentry_pe_exit_reason,
                                    new_pe_strike,
                                    reentry_pe_time,
                                    date_str,
                                )
                            )

                            # Update open position only if exit is in the future (not today)
                            if reentry_pe_exit_date and reentry_pe_exit_time:
                                try:
                                    reentry_pe_exit_date_dt = datetime.strptime(
                                        reentry_pe_exit_date, "%Y-%m-%d"
                                    )
                                    if reentry_pe_exit_date_dt > current_date:
                                        open_pe_position = {
                                            "entry_date": date_str,
                                            "entry_time": reentry_pe_time,
                                            "exit_date": reentry_pe_exit_date,
                                            "exit_time": reentry_pe_exit_time,
                                            "exit_reason": reentry_pe_exit_reason,  # Store exit reason for cooldown calculation
                                            "strike": new_pe_strike,
                                            "expiry_date": expiry_date_dt,
                                        }
                                    else:
                                        open_pe_position = None
                                except:
                                    open_pe_position = None

                            pe_reentry_count += 1
                            print(
                                f"  PE Re-entry #{pe_reentry_count} at {reentry_pe_time} @ {new_pe_entry_price} (Strike: {new_pe_strike})"
                            )

                # Loop again to see if another re-entry is possible (up to max_reentries)
        
        # Legacy code below (commented out for reference, but not used for positional):
        """
        # Process CE leg with re-entries
        if trade_ce and ce_entry_price is not None and ce_strike is not None:
            current_ce_entry_time = ce_entry_time
            current_ce_entry_price = ce_entry_price
            current_ce_strike = ce_strike
            ce_reentry_count = 0
            
            while True:
                # Calculate exit for current entry
                current_ce_exit_time = exit_time
                current_ce_exit_reason = "SCHEDULED_EXIT"
                
                # Check EMA exit if enabled
                if ema_enabled and use_ema_exit:
                    ce_ema_exit_time, ce_ema_exit_nifty, ce_ema_exit_fast, ce_ema_exit_slow = check_ema_exit_condition(
                        nifty_data, date_str, current_ce_entry_time, exit_time, is_bullish=False, interval_minutes=ema_interval
                    )
                    if ce_ema_exit_time is not None:
                        current_ce_exit_time = ce_ema_exit_time
                        # Round exit time to ema_interval if enabled
                        if round_to_ema_interval:
                            current_ce_exit_time = round_time_to_interval(current_ce_exit_time, ema_interval)
                        current_ce_exit_reason = "EMA_EXIT"
                
                # Check both target profit and stop loss, then use whichever happened first chronologically
                if current_ce_exit_reason != "EMA_EXIT":
                    ce_target_price = None
                    ce_target_time = None
                    ce_stop_loss_price = None
                    ce_stop_loss_time = None
                    
                    # Check target profit if enabled
                    if target_percentage > 0:
                        ce_target_price, ce_target_time = check_target_profit(
                            options_data, 'CE', current_ce_strike, current_ce_entry_time, current_ce_exit_time,
                            current_ce_entry_price, target_percentage
                        )
                    
                    # Check stop loss if enabled
                    if stop_loss_percentage > 0:
                        ce_stop_loss_price, ce_stop_loss_time = check_stop_loss(
                            options_data, 'CE', current_ce_strike, current_ce_entry_time, current_ce_exit_time,
                            current_ce_entry_price, stop_loss_percentage
                        )
                    
                    # Determine which happened first (if both triggered)
                    if ce_stop_loss_time is not None and ce_target_time is not None:
                        # Both triggered - use whichever happened first
                        stop_loss_dt = datetime.strptime(f"{date_str} {ce_stop_loss_time}", "%Y-%m-%d %H:%M:%S")
                        target_dt = datetime.strptime(f"{date_str} {ce_target_time}", "%Y-%m-%d %H:%M:%S")
                        if stop_loss_dt < target_dt:
                            current_ce_exit_time = ce_stop_loss_time
                            # Stop loss uses exact time, no rounding
                            current_ce_exit_reason = "STOP_LOSS"
                        else:
                            current_ce_exit_time = ce_target_time
                            # Target profit uses exact time, no rounding
                            current_ce_exit_reason = "TARGET_HIT"
                    elif ce_stop_loss_time is not None:
                        # Only stop loss triggered
                        current_ce_exit_time = ce_stop_loss_time
                        # Stop loss uses exact time, no rounding
                        current_ce_exit_reason = "STOP_LOSS"
                    elif ce_target_time is not None:
                        # Only target profit triggered
                        current_ce_exit_time = ce_target_time
                        # Target profit uses exact time, no rounding
                        current_ce_exit_reason = "TARGET_HIT"
                
                # Get exit price
                current_ce_exit_price = get_option_price_closest(options_data, 'CE', current_ce_strike, current_ce_exit_time)
                if current_ce_exit_price is None:
                    break
                
                # Store this trade
                ce_trades.append((current_ce_entry_price, current_ce_exit_price, current_ce_exit_time, current_ce_exit_reason, current_ce_strike, current_ce_entry_time))
                
                # Check if we can re-enter
                if reentry_enabled and ce_reentry_count < max_reentries:
                    # Calculate the earliest re-entry time (after cooldown if stop loss)
                    earliest_reentry_time = current_ce_exit_time
                    if current_ce_exit_reason == "STOP_LOSS" and stop_loss_cooldown_minutes > 0:
                        exit_dt = datetime.strptime(f"{date_str} {current_ce_exit_time}", "%Y-%m-%d %H:%M:%S")
                        cooldown_end_dt = exit_dt + timedelta(minutes=stop_loss_cooldown_minutes)
                        earliest_reentry_time = cooldown_end_dt.strftime("%H:%M:%S")
                    
                    # Check if earliest re-entry time is before the cutoff (optimization to avoid unnecessary EMA searches)
                    if not is_reentry_allowed(earliest_reentry_time, no_reentry_after):
                        # Already past cutoff, no re-entry allowed
                        break
                    
                    # Re-entry logic: use EMA conditions if reentry_based_on_ema_signals is enabled, or if EMA is enabled
                    reentry_ce_time = None
                    if reentry_based_on_ema_signals or ema_enabled:
                        # Check for BEARISH condition (F<S, N<F, N<S) from earliest re-entry time to scheduled exit
                        # Limit search to no_reentry_after if specified
                        search_end_time = exit_time
                        if no_reentry_after:
                            search_end_dt = datetime.strptime(f"{date_str} {no_reentry_after}", "%Y-%m-%d %H:%M:%S")
                            exit_dt = datetime.strptime(f"{date_str} {exit_time}", "%Y-%m-%d %H:%M:%S")
                            if search_end_dt < exit_dt:
                                search_end_time = no_reentry_after
                        reentry_ce_time, _, _, _ = find_ema_entry_times(
                            nifty_data, date_str, earliest_reentry_time, search_end_time, ema_interval, None, round_to_ema_interval, use_ema_cross_entry
                        )
                    else:
                        # When EMA is disabled and reentry_based_on_ema_signals is false, re-enter immediately after cooldown (if before exit_time)
                        earliest_reentry_dt = datetime.strptime(f"{date_str} {earliest_reentry_time}", "%Y-%m-%d %H:%M:%S")
                        exit_dt = datetime.strptime(f"{date_str} {exit_time}", "%Y-%m-%d %H:%M:%S")
                        if earliest_reentry_dt < exit_dt:
                            reentry_ce_time = earliest_reentry_time
                    
                    # When round_to_ema_interval is enabled, re-entry times are already at interval boundaries
                    # No additional rounding needed
                    
                    # Check if the actual re-entry time is before the cutoff
                    if reentry_ce_time is not None and is_reentry_allowed(reentry_ce_time, no_reentry_after):
                        # Round re-entry time to interval if round_to_ema_interval is enabled (for VIX check)
                        vix_check_time = reentry_ce_time
                        if round_to_ema_interval:
                            vix_check_time = round_time_to_interval(reentry_ce_time, ema_interval)
                        
                        # Check VIX EMA signal if enabled (independent of EMA signals enabled/disabled)
                        vix_ema_blocked = False
                        if vix_ema_signal and vix_data is not None:
                            vix_reentry_price = get_vix_price_at_time(vix_data, date_str, vix_check_time)
                            vix_reentry_base_ema = get_vix_base_ema_at_time(vix_data, date_str, vix_check_time)
                            if vix_reentry_price is not None and vix_reentry_base_ema is not None and vix_reentry_price > vix_reentry_base_ema:
                                print(f"    CE Re-entry blocked by VIX EMA signal: VIX price ({vix_reentry_price:.2f}) > base_ema ({vix_reentry_base_ema:.2f})")
                                vix_ema_blocked = True
                        
                        if not vix_ema_blocked:
                            # Re-entry found - get new strike and entry price
                            reentry_nifty = get_nifty_price_at_time(nifty_data, date_str, reentry_ce_time) or nifty_entry_price
                            new_ce_strike = find_atm_strike(reentry_nifty, strike_rounding) + (ce_offset * strike_rounding)
                            new_ce_entry_price = get_option_price_closest(options_data, 'CE', new_ce_strike, reentry_ce_time)
                            if new_ce_entry_price is not None:
                                ce_reentry_count += 1
                                current_ce_entry_time = reentry_ce_time
                                current_ce_entry_price = new_ce_entry_price
                                current_ce_strike = new_ce_strike
                                print(f"    CE Re-entry #{ce_reentry_count} at {reentry_ce_time} @ {new_ce_entry_price} (Strike: {new_ce_strike}, Nifty: {reentry_nifty:.2f})")
                                continue
                
                # No re-entry, done with CE
                break
        
        # Process PE leg with re-entries
        if trade_pe and pe_entry_price is not None and pe_strike is not None:
            current_pe_entry_time = pe_entry_time
            current_pe_entry_price = pe_entry_price
            current_pe_strike = pe_strike
            pe_reentry_count = 0
            
            while True:
                # Calculate exit for current entry
                current_pe_exit_time = exit_time
                current_pe_exit_reason = "SCHEDULED_EXIT"
                
                # Check EMA exit if enabled
                if ema_enabled and use_ema_exit:
                    pe_ema_exit_time, pe_ema_exit_nifty, pe_ema_exit_fast, pe_ema_exit_slow = check_ema_exit_condition(
                        nifty_data, date_str, current_pe_entry_time, exit_time, is_bullish=True, interval_minutes=ema_interval
                    )
                    if pe_ema_exit_time is not None:
                        current_pe_exit_time = pe_ema_exit_time
                        # Round exit time to ema_interval if enabled
                        if round_to_ema_interval:
                            current_pe_exit_time = round_time_to_interval(current_pe_exit_time, ema_interval)
                        current_pe_exit_reason = "EMA_EXIT"
                
                # Check both target profit and stop loss, then use whichever happened first chronologically
                if current_pe_exit_reason != "EMA_EXIT":
                    pe_target_price = None
                    pe_target_time = None
                    pe_stop_loss_price = None
                    pe_stop_loss_time = None
                    
                    # Check target profit if enabled
                    if target_percentage > 0:
                        pe_target_price, pe_target_time = check_target_profit(
                            options_data, 'PE', current_pe_strike, current_pe_entry_time, current_pe_exit_time,
                            current_pe_entry_price, target_percentage
                        )
                    
                    # Check stop loss if enabled
                    if stop_loss_percentage > 0:
                        pe_stop_loss_price, pe_stop_loss_time = check_stop_loss(
                            options_data, 'PE', current_pe_strike, current_pe_entry_time, current_pe_exit_time,
                            current_pe_entry_price, stop_loss_percentage
                        )
                    
                    # Determine which happened first (if both triggered)
                    if pe_stop_loss_time is not None and pe_target_time is not None:
                        # Both triggered - use whichever happened first
                        stop_loss_dt = datetime.strptime(f"{date_str} {pe_stop_loss_time}", "%Y-%m-%d %H:%M:%S")
                        target_dt = datetime.strptime(f"{date_str} {pe_target_time}", "%Y-%m-%d %H:%M:%S")
                        if stop_loss_dt < target_dt:
                            current_pe_exit_time = pe_stop_loss_time
                            # Stop loss uses exact time, no rounding
                            current_pe_exit_reason = "STOP_LOSS"
                        else:
                            current_pe_exit_time = pe_target_time
                            # Target profit uses exact time, no rounding
                            current_pe_exit_reason = "TARGET_HIT"
                    elif pe_stop_loss_time is not None:
                        # Only stop loss triggered
                        current_pe_exit_time = pe_stop_loss_time
                        # Stop loss uses exact time, no rounding
                        current_pe_exit_reason = "STOP_LOSS"
                    elif pe_target_time is not None:
                        # Only target profit triggered
                        current_pe_exit_time = pe_target_time
                        # Target profit uses exact time, no rounding
                        current_pe_exit_reason = "TARGET_HIT"
                
                # Get exit price
                current_pe_exit_price = get_option_price_closest(options_data, 'PE', current_pe_strike, current_pe_exit_time)
                if current_pe_exit_price is None:
                    break
                
                # Store this trade
                pe_trades.append((current_pe_entry_price, current_pe_exit_price, current_pe_exit_time, current_pe_exit_reason, current_pe_strike, current_pe_entry_time))
                
                # Check if we can re-enter
                if reentry_enabled and pe_reentry_count < max_reentries and is_reentry_allowed(current_pe_exit_time, no_reentry_after):
                    # Calculate the earliest re-entry time (after cooldown if stop loss)
                    earliest_reentry_time = current_pe_exit_time
                    if current_pe_exit_reason == "STOP_LOSS" and stop_loss_cooldown_minutes > 0:
                        exit_dt = datetime.strptime(f"{date_str} {current_pe_exit_time}", "%Y-%m-%d %H:%M:%S")
                        cooldown_end_dt = exit_dt + timedelta(minutes=stop_loss_cooldown_minutes)
                        earliest_reentry_time = cooldown_end_dt.strftime("%H:%M:%S")
                    
                    # Re-entry logic: use EMA conditions if reentry_based_on_ema_signals is enabled, or if EMA is enabled
                    reentry_pe_time = None
                    if reentry_based_on_ema_signals or ema_enabled:
                        # Check for BULLISH condition (F>S, N>F, N>S) from earliest re-entry time to scheduled exit
                        _, reentry_pe_time, _, _ = find_ema_entry_times(
                            nifty_data, date_str, earliest_reentry_time, exit_time, ema_interval, None, round_to_ema_interval, use_ema_cross_entry
                        )
                    else:
                        # When EMA is disabled and reentry_based_on_ema_signals is false, re-enter immediately after cooldown (if before exit_time)
                        earliest_reentry_dt = datetime.strptime(f"{date_str} {earliest_reentry_time}", "%Y-%m-%d %H:%M:%S")
                        exit_dt = datetime.strptime(f"{date_str} {exit_time}", "%Y-%m-%d %H:%M:%S")
                        if earliest_reentry_dt < exit_dt:
                            reentry_pe_time = earliest_reentry_time
                    
                    # When round_to_ema_interval is enabled, re-entry times are already at interval boundaries
                    # No additional rounding needed
                    
                    # Check if the actual re-entry time is before the cutoff
                    if reentry_pe_time is not None and is_reentry_allowed(reentry_pe_time, no_reentry_after):
                        # Round re-entry time to interval if round_to_ema_interval is enabled (for VIX check)
                        vix_check_time = reentry_pe_time
                        if round_to_ema_interval:
                            vix_check_time = round_time_to_interval(reentry_pe_time, ema_interval)
                        
                        # Check VIX EMA signal if enabled (independent of EMA signals enabled/disabled)
                        vix_ema_blocked = False
                        if vix_ema_signal and vix_data is not None:
                            vix_reentry_price = get_vix_price_at_time(vix_data, date_str, vix_check_time)
                            vix_reentry_base_ema = get_vix_base_ema_at_time(vix_data, date_str, vix_check_time)
                            vix_reentry_price = get_vix_price_at_time(vix_data, date_str, reentry_pe_time)
                            vix_reentry_base_ema = get_vix_base_ema_at_time(vix_data, date_str, reentry_pe_time)
                            if vix_reentry_price is not None and vix_reentry_base_ema is not None and vix_reentry_price > vix_reentry_base_ema:
                                print(f"    PE Re-entry blocked by VIX EMA signal: VIX price ({vix_reentry_price:.2f}) > base_ema ({vix_reentry_base_ema:.2f})")
                                vix_ema_blocked = True
                        
                        if not vix_ema_blocked:
                            # Re-entry found - get new strike and entry price
                            reentry_nifty = get_nifty_price_at_time(nifty_data, date_str, reentry_pe_time) or nifty_entry_price
                            new_pe_strike = find_atm_strike(reentry_nifty, strike_rounding) + (pe_offset * strike_rounding)
                            new_pe_entry_price = get_option_price_closest(options_data, 'PE', new_pe_strike, reentry_pe_time)
                            if new_pe_entry_price is not None:
                                pe_reentry_count += 1
                                current_pe_entry_time = reentry_pe_time
                                current_pe_entry_price = new_pe_entry_price
                                current_pe_strike = new_pe_strike
                                print(f"    PE Re-entry #{pe_reentry_count} at {reentry_pe_time} @ {new_pe_entry_price} (Strike: {new_pe_strike}, Nifty: {reentry_nifty:.2f})")
                                continue
                
                # No re-entry, done with PE
                break
        """
        
        # Calculate total P&L across all trades (initial + re-entries)
        ce_pnl = 0.0
        pe_pnl = 0.0
        for entry_price, exit_price, _, _, _, _, _, _ in ce_trades:
            ce_pnl += (entry_price - exit_price) * lot_size * lot_multiple
        for entry_price, exit_price, _, _, _, _, _, _ in pe_trades:
            pe_pnl += (entry_price - exit_price) * lot_size * lot_multiple
        total_pnl = ce_pnl + pe_pnl
        
        # Get final exit times and reasons (from last trade)
        ce_final_exit_date = ce_trades[-1][2] if ce_trades else None
        ce_final_exit_time = ce_trades[-1][3] if ce_trades else None
        ce_final_exit_reason = ce_trades[-1][4] if ce_trades else None
        pe_final_exit_date = pe_trades[-1][2] if pe_trades else None
        pe_final_exit_time = pe_trades[-1][3] if pe_trades else None
        pe_final_exit_reason = pe_trades[-1][4] if pe_trades else None
        
        # Store each trade separately (initial + re-entries)
        # Track each leg independently - no pairing by index
        trade_counter = 0
        
        # Process CE trades independently
        for ce_idx, ce_trade in enumerate(ce_trades):
            trade_counter += 1
            # Tuple format: (entry_price, exit_price, exit_date, exit_time, exit_reason, strike, entry_time, entry_date)
            ce_entry_date_trade = ce_trade[7]  # entry_date from trade tuple
            ce_entry_time_trade = ce_trade[6]  # entry_time from trade tuple
            ce_exit_date_trade = ce_trade[2]  # exit_date from trade tuple
            ce_exit_time_trade = ce_trade[3]  # exit_time from trade tuple
            
            # Get Nifty prices at trade entry/exit
            trade_nifty_entry = get_nifty_price_at_time(nifty_data, ce_entry_date_trade, ce_entry_time_trade) or nifty_entry_price
            trade_nifty_exit = get_nifty_price_at_time(nifty_data, ce_exit_date_trade, ce_exit_time_trade) or nifty_exit_price
            
            # Get EMA values at trade entry/exit
            trade_fast_ema_entry = None
            trade_slow_ema_entry = None
            trade_fast_ema_exit = None
            trade_slow_ema_exit = None
            if ema_enabled:
                trade_fast_ema_entry, trade_slow_ema_entry = get_ema_from_nifty_data(nifty_data, ce_entry_date_trade, ce_entry_time_trade)
                trade_fast_ema_exit, trade_slow_ema_exit = get_ema_from_nifty_data(nifty_data, ce_exit_date_trade, ce_exit_time_trade)
            
            # Calculate P&L for this trade
            trade_ce_pnl = (ce_trade[0] - ce_trade[1]) * lot_size * lot_multiple
            
            # Determine entry reason: BEARISH for first entry, RE_BEAR for re-entries
            if ce_idx == 0:
                # First entry - use original entry reason, but ensure it's BEARISH for CE
                if entry_reason in ['BEARISH', 'EMA_BEARISH']:
                    trade_entry_reason = "BEARISH"
                elif entry_reason == 'EMA_MIXED':
                    trade_entry_reason = "BEARISH"  # CE leg from MIXED is BEARISH
                else:
                    trade_entry_reason = "BEARISH"  # Default for CE
            else:
                trade_entry_reason = "RE_BEAR"  # Re-entry for CE (shouldn't happen for positional)
            
            # Build result for this CE trade
            result = {
                "date": ce_entry_date_trade,
                "trade_number": trade_counter,
                "entry_time": f"{ce_entry_date_trade} {ce_entry_time_trade}",
                "exit_time": f"{ce_exit_date_trade} {ce_exit_time_trade}",
                "entry_reason": trade_entry_reason,
                "fast_ema_at_entry": round(trade_fast_ema_entry, 2) if trade_fast_ema_entry is not None else None,
                "slow_ema_at_entry": round(trade_slow_ema_entry, 2) if trade_slow_ema_entry is not None else None,
                "fast_ema_at_exit": round(trade_fast_ema_exit, 2) if trade_fast_ema_exit is not None else None,
                "slow_ema_at_exit": round(trade_slow_ema_exit, 2) if trade_slow_ema_exit is not None else None,
                "expiry_date": expiry_date_str,
                "vix_at_entry": round(vix_at_entry, 2) if vix_at_entry is not None else None,
                "vix_at_exit": None,
                "nifty_entry_price": round(trade_nifty_entry, 2) if trade_nifty_entry else None,
                "nifty_exit_price": round(trade_nifty_exit, 2) if trade_nifty_exit else None,
                "ce_strike": ce_trade[5],  # strike from trade tuple
                "ce_entry_price": round(ce_trade[0], 2),  # entry_price from trade tuple
                "ce_entry_time": f"{ce_entry_date_trade} {ce_entry_time_trade}",  # entry_time from trade tuple
                "ce_exit_price": round(ce_trade[1], 2),  # exit_price from trade tuple
                "ce_exit_time": f"{ce_exit_date_trade} {ce_exit_time_trade}",  # exit_time from trade tuple
                "ce_exit_reason": ce_trade[4],  # exit_reason from trade tuple
                "ce_stopped": ce_trade[4] == "STOP_LOSS",
                "ce_pnl": round(trade_ce_pnl, 2),
                "pe_strike": None,
                "pe_entry_price": None,
                "pe_entry_time": None,
                "pe_exit_price": None,
                "pe_exit_time": None,
                "pe_exit_reason": None,
                "pe_stopped": False,
                "pe_pnl": 0.0,
                "total_pnl": round(trade_ce_pnl, 2)
            }
            
            results.append(result)
            
            # Print trade details
            ce_info = f"CE Strike {ce_trade[5]}: Entry {ce_trade[0]} on {ce_entry_date_trade} at {ce_entry_time_trade}, Exit {ce_trade[1]} on {ce_exit_date_trade} at {ce_exit_time_trade} ({ce_trade[4]}), P&L: {trade_ce_pnl}"
            trade_label = f"Trade #{trade_counter}" if len(ce_trades) > 1 or len(pe_trades) > 0 else "Trade"
            print(f"  {trade_label}: {ce_info}")
            print(f"    Total P&L: {trade_ce_pnl}")
        
        # Process PE trades independently
        for pe_idx, pe_trade in enumerate(pe_trades):
            trade_counter += 1
            # Tuple format: (entry_price, exit_price, exit_date, exit_time, exit_reason, strike, entry_time, entry_date)
            pe_entry_date_trade = pe_trade[7]  # entry_date from trade tuple
            pe_entry_time_trade = pe_trade[6]  # entry_time from trade tuple
            pe_exit_date_trade = pe_trade[2]  # exit_date from trade tuple
            pe_exit_time_trade = pe_trade[3]  # exit_time from trade tuple
            
            # Get Nifty prices at trade entry/exit
            trade_nifty_entry = get_nifty_price_at_time(nifty_data, pe_entry_date_trade, pe_entry_time_trade) or nifty_entry_price
            trade_nifty_exit = get_nifty_price_at_time(nifty_data, pe_exit_date_trade, pe_exit_time_trade) or nifty_exit_price
            
            # Get EMA values at trade entry/exit
            trade_fast_ema_entry = None
            trade_slow_ema_entry = None
            trade_fast_ema_exit = None
            trade_slow_ema_exit = None
            if ema_enabled:
                trade_fast_ema_entry, trade_slow_ema_entry = get_ema_from_nifty_data(nifty_data, pe_entry_date_trade, pe_entry_time_trade)
                trade_fast_ema_exit, trade_slow_ema_exit = get_ema_from_nifty_data(nifty_data, pe_exit_date_trade, pe_exit_time_trade)
            
            # Calculate P&L for this trade
            trade_pe_pnl = (pe_trade[0] - pe_trade[1]) * lot_size * lot_multiple
            
            # Determine entry reason: BULLISH for first entry, RE_BULL for re-entries
            if pe_idx == 0:
                # First entry - use original entry reason, but ensure it's BULLISH for PE
                if entry_reason in ['BULLISH', 'EMA_BULLISH']:
                    trade_entry_reason = "BULLISH"
                elif entry_reason == 'EMA_MIXED':
                    trade_entry_reason = "BULLISH"  # PE leg from MIXED is BULLISH
                else:
                    trade_entry_reason = "BULLISH"  # Default for PE
            else:
                trade_entry_reason = "RE_BULL"  # Re-entry for PE (shouldn't happen for positional)
            
            # Build result for this PE trade
            result = {
                "date": pe_entry_date_trade,
                "trade_number": trade_counter,
                "entry_time": f"{pe_entry_date_trade} {pe_entry_time_trade}",
                "exit_time": f"{pe_exit_date_trade} {pe_exit_time_trade}",
                "entry_reason": trade_entry_reason,
                "fast_ema_at_entry": round(trade_fast_ema_entry, 2) if trade_fast_ema_entry is not None else None,
                "slow_ema_at_entry": round(trade_slow_ema_entry, 2) if trade_slow_ema_entry is not None else None,
                "fast_ema_at_exit": round(trade_fast_ema_exit, 2) if trade_fast_ema_exit is not None else None,
                "slow_ema_at_exit": round(trade_slow_ema_exit, 2) if trade_slow_ema_exit is not None else None,
                "expiry_date": expiry_date_str,
                "vix_at_entry": round(vix_at_entry, 2) if vix_at_entry is not None else None,
                "vix_at_exit": None,
                "nifty_entry_price": round(trade_nifty_entry, 2) if trade_nifty_entry else None,
                "nifty_exit_price": round(trade_nifty_exit, 2) if trade_nifty_exit else None,
                "ce_strike": None,
                "ce_entry_price": None,
                "ce_entry_time": None,
                "ce_exit_price": None,
                "ce_exit_time": None,
                "ce_exit_reason": None,
                "ce_stopped": False,
                "ce_pnl": 0.0,
                "pe_strike": pe_trade[5],  # strike from trade tuple
                "pe_entry_price": round(pe_trade[0], 2),  # entry_price from trade tuple
                "pe_entry_time": f"{pe_entry_date_trade} {pe_entry_time_trade}",  # entry_time from trade tuple
                "pe_exit_price": round(pe_trade[1], 2),  # exit_price from trade tuple
                "pe_exit_time": f"{pe_exit_date_trade} {pe_exit_time_trade}",  # exit_time from trade tuple
                "pe_exit_reason": pe_trade[4],  # exit_reason from trade tuple
                "pe_stopped": pe_trade[4] == "STOP_LOSS",
                "pe_pnl": round(trade_pe_pnl, 2),
                "total_pnl": round(trade_pe_pnl, 2)
            }
            
            results.append(result)
            
            # Print trade details
            pe_info = f"PE Strike {pe_trade[5]}: Entry {pe_trade[0]} on {pe_entry_date_trade} at {pe_entry_time_trade}, Exit {pe_trade[1]} on {pe_exit_date_trade} at {pe_exit_time_trade} ({pe_trade[4]}), P&L: {trade_pe_pnl}"
            trade_label = f"Trade #{trade_counter}" if len(ce_trades) > 0 or len(pe_trades) > 1 else "Trade"
            print(f"  {trade_label}: {pe_info}")
            print(f"    Total P&L: {trade_pe_pnl}")
        
        current_date += timedelta(days=1)
    
    return results


def calculate_drawdown_metrics(results: List[Dict]) -> tuple:
    """Calculate max drawdown and max drawdown days from results"""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED, VIX_EMA_SIGNAL_BLOCKED, EMA_NEUTRAL) for drawdown calculation
    actual_trades = [r for r in results if r.get('entry_reason') not in ['VIX_THRESHOLD_EXCEEDED', 'VIX_EMA_SIGNAL_BLOCKED', 'EMA_NEUTRAL']]
    
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


def save_results(results: List[Dict], output_file: str, per_order_charges: float = 0.0, lot_multiple: int = 1) -> Dict:
    """Save backtest results to JSON file. Returns the summary dictionary."""
    # Filter out skipped trades (VIX_THRESHOLD_EXCEEDED, VIX_EMA_SIGNAL_BLOCKED, and EMA_NEUTRAL) for trade statistics
    actual_trades = [r for r in results if r.get('entry_reason') not in ['VIX_THRESHOLD_EXCEEDED', 'VIX_EMA_SIGNAL_BLOCKED', 'EMA_NEUTRAL']]
    
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
    
    return summary


def save_backtest_to_database(config: Dict, summary: Dict) -> int:
    """Save backtest configuration and summary to database"""
    try:
        record_id = save_backtest_history(config, summary)
        print(f"Backtest history saved to database with ID: {record_id}")
        return record_id
    except Exception as e:
        print(f"Error saving backtest history to database: {e}")
        return -1


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
    per_order_charges = config['basic_settings'].get('per_order_charges', 100)
    lot_multiple = config['basic_settings'].get('lot_multiple', 1)
    summary = save_results(results, output_json, per_order_charges, lot_multiple)
    
    # Save to database
    save_backtest_to_database(config, summary)
    
    print("\nBacktest completed successfully!")
    print(f"View results in web app: python3 app.py")


if __name__ == "__main__":
    main()

