#!/usr/bin/env python3
"""
Nifty Options EOD Backtest — Hold Until SL/Target or Expiry

Same entry logic as run_eod_backtest.py (entry at 15:18, VIX filter, 0DTE handling).
Exit logic: no fixed next-day exit. Position is held until:
- Stop loss is triggered (price increases by stop_loss_percentage), OR
- Target profit is reached (price decreases by target_percentage), OR
- Expiry date (force exit at 15:17 on expiry day if neither hit)

Each leg (CE/PE) exits independently when its SL or target is hit. Day-by-day from
the next trading day after entry until expiry; each day checks 09:18–15:17.
If both stop_loss_percentage and target_percentage are 0, both legs exit at 15:17 on expiry day.

SHORT options: P&L = (Entry Price - Exit Price) × Lot Size × Lot Multiple.
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


def parse_expiry_date(expiry_date_str: str) -> Optional[datetime]:
    """Parse expiry date from "DD-MMM-YYYY" format to datetime object"""
    try:
        return datetime.strptime(expiry_date_str, "%d-%b-%Y")
    except:
        try:
            return datetime.strptime(expiry_date_str, "%d-%b-%y")
        except:
            return None


def get_nifty_price_at_time(nifty_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get Nifty open price at specific date and time"""
    date_key = date
    if date_key not in nifty_data:
        return None
    
    # time_str is in format "HH:MM:SS"
    for entry in nifty_data[date_key]:
        entry_time = entry.get('time', '')
        if entry_time.startswith(time_str) or entry_time.endswith(time_str):
            return entry.get('open')
    return None


def get_vix_price_at_time(vix_data: Dict, date: str, time_str: str) -> Optional[float]:
    """Get VIX open price at specific date and time"""
    date_key = date
    if date_key not in vix_data:
        return None
    
    for entry in vix_data[date_key]:
        entry_time = entry.get('time', '')
        if entry_time.startswith(time_str) or entry_time.endswith(time_str):
            return entry.get('open')
    return None


def find_atm_strike(nifty_price: float, strike_rounding: int = 50) -> int:
    """Find ATM strike price"""
    return round_to_strike(nifty_price, strike_rounding)


def find_closest_strike(option_section: Dict, target_strike: int) -> Optional[int]:
    """Find closest available strike in option section"""
    if not option_section:
        return None
    
    available_strikes = [int(s) for s in option_section.keys() if s.isdigit()]
    if not available_strikes:
        return None
    
    closest_strike = min(available_strikes, key=lambda x: abs(x - target_strike))
    return closest_strike


def get_option_price_closest(options_data: Dict, option_type: str, strike: int, time_str: str) -> Optional[float]:
    """Get option price closest to specified time"""
    if not options_data or 'data' not in options_data:
        return None
    
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        # Try to find closest available strike
        closest_strike = find_closest_strike(option_section, strike)
        if closest_strike is not None:
            strike_key = str(closest_strike)
            print(f"    Using closest available {option_type} strike {closest_strike} instead of {strike}")
        else:
            return None
    
    strike_data = option_section[strike_key]
    
    # Find closest time entry
    closest_price = None
    min_time_diff = float('inf')
    
    for entry in strike_data:
        entry_time = entry.get('datetime', entry.get('time', ''))
        if not entry_time:
            continue
        
        # Extract time part
        if ' ' in entry_time:
            entry_time_only = entry_time.split(' ')[1]
        else:
            entry_time_only = entry_time
        
        # Compare times
        try:
            entry_dt = datetime.strptime(entry_time_only, "%H:%M:%S")
            target_dt = datetime.strptime(time_str, "%H:%M:%S")
            time_diff = abs((entry_dt - target_dt).total_seconds())
            
            if time_diff < min_time_diff:
                min_time_diff = time_diff
                closest_price = entry.get('open')
        except:
            continue
    
    return closest_price


def get_option_price_on_date(options_data_path: str, option_type: str, strike: int, 
                             date_str: str, time_str: str) -> Optional[float]:
    """Get option price on a specific date and time"""
    year = datetime.strptime(date_str, "%Y-%m-%d").year
    options_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
    
    options_data = load_options_data(options_file)
    if not options_data:
        return None
    
    return get_option_price_closest(options_data, option_type, strike, time_str)


def check_stop_loss_or_target_exit_day(options_data: Dict, option_type: str, strike: int,
                                       entry_date: str, entry_time: str, exit_date: str, exit_time: str,
                                       entry_price: float, stop_loss_percentage: float,
                                       target_percentage: float) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[str]]:
    """
    Check if stop loss or target profit is hit on exit day (for EOD backtest).
    For SHORT positions:
    - Stop loss: price increases by stop_loss_percentage
    - Target profit: price decreases by target_percentage
    
    Returns: (exit_price, exit_date, exit_time, exit_reason) or (None, None, None, None) if not hit
    """
    if not options_data or 'data' not in options_data:
        return None, None, None, None
    
    option_section = options_data['data'].get('call' if option_type == 'CE' else 'put')
    if not option_section:
        return None, None, None, None
    
    strike_key = str(strike)
    if strike_key not in option_section:
        return None, None, None, None
    
    strike_data = option_section[strike_key]
    
    # Calculate stop loss and target prices for SHORT
    stop_loss_price = None
    target_price = None
    
    if stop_loss_percentage > 0:
        stop_loss_price = entry_price * (1 + stop_loss_percentage / 100)
    if target_percentage > 0:
        target_price = entry_price * (1 - target_percentage / 100)
    
    # Parse times - check from start of exit day (09:18) until force exit time (15:17)
    try:
        # Start checking from 09:18 on exit day
        check_start_dt = datetime.strptime(f"{exit_date} 09:18:00", "%Y-%m-%d %H:%M:%S")
        check_end_dt = datetime.strptime(f"{exit_date} {exit_time}", "%Y-%m-%d %H:%M:%S")
    except:
        return None, None, None, None
    
    # Check prices on exit day
    earliest_exit = None
    earliest_exit_price = None
    earliest_exit_reason = None
    
    for entry in strike_data:
        entry_datetime_str = entry.get('datetime')
        if not entry_datetime_str:
            continue
        
        try:
            price_datetime = datetime.strptime(entry_datetime_str, "%Y-%m-%d %H:%M:%S")
            price = entry.get('open')
            
            if price is None:
                continue
            
            # Only check prices on exit day between check_start and check_end
            if price_datetime < check_start_dt or price_datetime > check_end_dt:
                continue
            
            # Check stop loss first (higher priority for risk management)
            if stop_loss_price is not None and price >= stop_loss_price:
                if earliest_exit is None or price_datetime < earliest_exit:
                    earliest_exit = price_datetime
                    earliest_exit_price = price
                    earliest_exit_reason = "STOP_LOSS"
            
            # Check target profit (only if stop loss hasn't triggered yet)
            if target_price is not None and price <= target_price:
                if earliest_exit is None or price_datetime < earliest_exit:
                    earliest_exit = price_datetime
                    earliest_exit_price = price
                    earliest_exit_reason = "TARGET_PROFIT"
        
        except:
            continue
    
    if earliest_exit is not None and earliest_exit_price is not None:
        return earliest_exit_price, earliest_exit.strftime("%Y-%m-%d"), earliest_exit.strftime("%H:%M:%S"), earliest_exit_reason
    
    return None, None, None, None


def _next_trading_day(d: datetime) -> datetime:
    """Return next trading day (skip weekends)."""
    d = d + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def run_backtest(config: Dict) -> List[Dict]:
    """Run EOD backtest: enter at 15:18, hold until stop_loss/target hit or expiry (no fixed next-day exit)."""
    results = []
    
    # Fixed entry and exit times
    entry_time = "15:20:00"
    exit_time = "15:19:00"  # End-of-day time for force exit on expiry
    
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
    
    strike_rounding = config['basic_settings']['strike_rounding']
    ce_offset = config['basic_settings']['ce_strike_offset']
    pe_offset = config['basic_settings']['pe_strike_offset']
    lot_size = config['basic_settings']['lot_size']
    lot_multiple = config['basic_settings'].get('lot_multiple', 1)
    per_order_charges = config['basic_settings'].get('per_order_charges', 100)
    stop_loss_percentage = config['options'].get('stop_loss_percentage', 0)
    target_percentage = config['options'].get('target_percentage', 0)
    
    options_data_path = config['data_paths']['options_data']
    
    current_date = start_date
    last_exit_date = None  # last exit date of previous trade (no open leg at 15:18 on or after this day)
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Skip weekends
        if current_date.weekday() >= 5:
            current_date += timedelta(days=1)
            continue
        
        # Do not enter if any leg from a previous trade is still open at 15:18 today
        if last_exit_date is not None and current_date.date() < last_exit_date:
            current_date = _next_trading_day(current_date)
            continue
        
        print(f"Processing {date_str}...")
        
        # Determine options file - check if it's 0DTE
        year = current_date.year
        regular_file = f"{options_data_path}/{year}/nifty_options_{date_str}.json"
        next_expiry_file = f"{options_data_path}/{year}/nifty_options_{date_str}_next_expiry.json"
        
        # First, check regular file to see if it's 0DTE
        options_data = load_options_data(regular_file)
        
        if options_data:
            expiry_date_str = options_data.get('expiry_date', None)
            if expiry_date_str:
                expiry_date_dt = parse_expiry_date(expiry_date_str)
                if expiry_date_dt and expiry_date_dt.date() == current_date.date():
                    # It's 0DTE - use next_expiry file instead (skip trading on 0DTE)
                    print(f"  Detected 0DTE expiry on {date_str}, using next_expiry file instead")
                    options_data = load_options_data(next_expiry_file)
                    if not options_data:
                        print(f"  Next expiry file not found, skipping trade on {date_str}")
                        current_date += timedelta(days=1)
                        continue
                    # Verify next_expiry file is not also 0DTE
                    next_expiry_date_str = options_data.get('expiry_date', None)
                    if next_expiry_date_str:
                        next_expiry_date_dt = parse_expiry_date(next_expiry_date_str)
                        if next_expiry_date_dt and next_expiry_date_dt.date() == current_date.date():
                            print(f"  Next expiry file is also 0DTE, skipping trade on {date_str}")
                            current_date += timedelta(days=1)
                            continue
        else:
            # Regular file doesn't exist, try next_expiry
            options_data = load_options_data(next_expiry_file)
            if not options_data:
                print(f"  No options data found for {date_str}")
                current_date += timedelta(days=1)
                continue
        
        # Get expiry date from options data
        expiry_date_str = options_data.get('expiry_date', None)
        if not expiry_date_str:
            print(f"  No expiry date in options data for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Get Nifty price at entry time (15:28)
        nifty_entry_price = get_nifty_price_at_time(nifty_data, date_str, entry_time)
        if not nifty_entry_price:
            print(f"  Missing Nifty price at entry time {entry_time} for {date_str}")
            current_date += timedelta(days=1)
            continue
        
        # Check VIX threshold if configured
        if vix_data is not None and vix_threshold is not None:
            vix_entry_price = get_vix_price_at_time(vix_data, date_str, entry_time)
            if vix_entry_price is not None and vix_entry_price > vix_threshold:
                print(f"  VIX threshold exceeded: {vix_entry_price} > {vix_threshold}, skipping trade")
                current_date += timedelta(days=1)
                continue
        
        # Calculate strikes
        ce_strike = find_atm_strike(nifty_entry_price, strike_rounding) + (ce_offset * strike_rounding)
        pe_strike = find_atm_strike(nifty_entry_price, strike_rounding) + (pe_offset * strike_rounding)
        
        # Get option prices at entry time (function will use closest strike if exact doesn't exist)
        ce_entry_price = get_option_price_closest(options_data, 'CE', ce_strike, entry_time)
        pe_entry_price = get_option_price_closest(options_data, 'PE', pe_strike, entry_time)
        
        if ce_entry_price is None or pe_entry_price is None:
            print(f"  Missing option prices at entry time for {date_str} (CE strike {ce_strike}, PE strike {pe_strike})")
            current_date += timedelta(days=1)
            continue
        
        # Update strikes to actual strikes used (in case closest strike was used)
        if 'data' in options_data:
            ce_section = options_data['data'].get('call', {})
            pe_section = options_data['data'].get('put', {})
            if str(ce_strike) not in ce_section:
                ce_strike = find_closest_strike(ce_section, ce_strike) or ce_strike
            if str(pe_strike) not in pe_section:
                pe_strike = find_closest_strike(pe_section, pe_strike) or pe_strike
        
        print(f"  Entry at {entry_time}: CE Strike {ce_strike} @ {ce_entry_price}, PE Strike {pe_strike} @ {pe_entry_price}")
        
        # Expiry date: hold until SL/target or expiry (no fixed next-day exit)
        expiry_dt = parse_expiry_date(expiry_date_str)
        expiry_date_obj = expiry_dt.date() if expiry_dt else current_date.date()
        # Don't go past backtest end_date
        last_exit_date_obj = min(expiry_date_obj, end_date.date())
        
        exit_date = _next_trading_day(current_date)
        ce_exit_price = None
        ce_exit_date_str = None
        ce_exit_time_str = exit_time
        ce_exit_reason = "FORCE_EXIT"
        pe_exit_price = None
        pe_exit_date_str = None
        pe_exit_time_str = exit_time
        pe_exit_reason = "FORCE_EXIT"
        
        # Day-by-day from next trading day until expiry (or end_date), check SL/target for each leg
        while exit_date.date() <= last_exit_date_obj:
            exit_date_str_loop = exit_date.strftime("%Y-%m-%d")
            exit_options_file = f"{options_data_path}/{exit_date.year}/nifty_options_{exit_date_str_loop}.json"
            exit_options_data = load_options_data(exit_options_file)
            if not exit_options_data:
                exit_date = _next_trading_day(exit_date)
                continue
            
            # CE: check SL/target on this day if not yet exited
            if ce_exit_price is None:
                if stop_loss_percentage > 0 or target_percentage > 0:
                    ce_sl_price, ce_sl_date, ce_sl_time, ce_sl_reason = check_stop_loss_or_target_exit_day(
                        exit_options_data, 'CE', ce_strike, date_str, entry_time, exit_date_str_loop, exit_time,
                        ce_entry_price, stop_loss_percentage, target_percentage
                    )
                    if ce_sl_price is not None:
                        ce_exit_price = ce_sl_price
                        ce_exit_date_str = ce_sl_date
                        ce_exit_time_str = ce_sl_time
                        ce_exit_reason = ce_sl_reason or "STOP_LOSS"
                if ce_exit_price is None and exit_date.date() == last_exit_date_obj:
                    ce_exit_price = get_option_price_closest(exit_options_data, 'CE', ce_strike, exit_time)
                    if ce_exit_price is not None:
                        ce_exit_date_str = exit_date_str_loop
                        ce_exit_reason = "FORCE_EXIT"
            
            # PE: check SL/target on this day if not yet exited
            if pe_exit_price is None:
                if stop_loss_percentage > 0 or target_percentage > 0:
                    pe_sl_price, pe_sl_date, pe_sl_time, pe_sl_reason = check_stop_loss_or_target_exit_day(
                        exit_options_data, 'PE', pe_strike, date_str, entry_time, exit_date_str_loop, exit_time,
                        pe_entry_price, stop_loss_percentage, target_percentage
                    )
                    if pe_sl_price is not None:
                        pe_exit_price = pe_sl_price
                        pe_exit_date_str = pe_sl_date
                        pe_exit_time_str = pe_sl_time
                        pe_exit_reason = pe_sl_reason or "STOP_LOSS"
                if pe_exit_price is None and exit_date.date() == last_exit_date_obj:
                    pe_exit_price = get_option_price_closest(exit_options_data, 'PE', pe_strike, exit_time)
                    if pe_exit_price is not None:
                        pe_exit_date_str = exit_date_str_loop
                        pe_exit_reason = "FORCE_EXIT"
            
            if ce_exit_price is not None and pe_exit_price is not None:
                break
            exit_date = _next_trading_day(exit_date)
        
        # Force exit any leg still open at last date (expiry or end_date)
        force_exit_date_str = last_exit_date_obj.strftime("%Y-%m-%d")
        force_options_file = f"{options_data_path}/{last_exit_date_obj.year}/nifty_options_{force_exit_date_str}.json"
        force_options_data = load_options_data(force_options_file)
        if force_options_data:
            if ce_exit_price is None:
                ce_exit_price = get_option_price_closest(force_options_data, 'CE', ce_strike, exit_time)
                ce_exit_date_str = force_exit_date_str
                ce_exit_reason = "FORCE_EXIT"
            if pe_exit_price is None:
                pe_exit_price = get_option_price_closest(force_options_data, 'PE', pe_strike, exit_time)
                pe_exit_date_str = force_exit_date_str
                pe_exit_reason = "FORCE_EXIT"
        
        if ce_exit_price is None or pe_exit_price is None:
            print(f"  Could not get exit prices (CE={ce_exit_price}, PE={pe_exit_price}), skipping trade")
            current_date += timedelta(days=1)
            continue
        
        exit_date_str = ce_exit_date_str if ce_exit_date_str else pe_exit_date_str
        
        # Calculate P&L for SHORT positions
        ce_pnl = (ce_entry_price - ce_exit_price) * lot_size * lot_multiple
        pe_pnl = (pe_entry_price - pe_exit_price) * lot_size * lot_multiple
        total_pnl = ce_pnl + pe_pnl
        
        # Nifty/VIX at exit: use later of the two leg exit dates/times for display
        latest_exit_date = (ce_exit_date_str or "") if (ce_exit_date_str or "") >= (pe_exit_date_str or "") else (pe_exit_date_str or "")
        if latest_exit_date == (ce_exit_date_str or ""):
            latest_exit_time = ce_exit_time_str
        else:
            latest_exit_time = pe_exit_time_str
        if not latest_exit_date:
            latest_exit_date = exit_date_str
        nifty_exit_price = get_nifty_price_at_time(nifty_data, latest_exit_date, latest_exit_time)
        if not nifty_exit_price:
            nifty_exit_price = get_nifty_price_at_time(nifty_data, latest_exit_date, exit_time)
        
        vix_at_entry = None
        vix_at_exit = None
        if vix_data is not None:
            vix_at_entry = get_vix_price_at_time(vix_data, date_str, entry_time)
            vix_at_exit = get_vix_price_at_time(vix_data, latest_exit_date, latest_exit_time)
            if vix_at_exit is None:
                vix_at_exit = get_vix_price_at_time(vix_data, latest_exit_date, exit_time)
        
        result = {
            "date": date_str,
            "trade_number": 1,
            "entry_time": f"{date_str} {entry_time}",
            "exit_time": f"{latest_exit_date} {exit_time}",
            "entry_reason": "EOD_ENTRY",
            "fast_ema_at_entry": None,
            "slow_ema_at_entry": None,
            "fast_ema_at_exit": None,
            "slow_ema_at_exit": None,
            "expiry_date": expiry_date_str,
            "vix_at_entry": round(vix_at_entry, 2) if vix_at_entry is not None else None,
            "vix_at_exit": round(vix_at_exit, 2) if vix_at_exit is not None else None,
            "nifty_entry_price": round(nifty_entry_price, 2),
            "nifty_exit_price": round(nifty_exit_price, 2),
            "ce_strike": ce_strike,
            "ce_entry_price": round(ce_entry_price, 2),
            "ce_entry_time": f"{date_str} {entry_time}",
            "ce_exit_price": round(ce_exit_price, 2),
            "ce_exit_time": f"{ce_exit_date_str} {ce_exit_time_str}",
            "ce_exit_reason": ce_exit_reason,
            "ce_stopped": ce_exit_reason == "STOP_LOSS",
            "ce_pnl": round(ce_pnl, 2),
            "pe_strike": pe_strike,
            "pe_entry_price": round(pe_entry_price, 2),
            "pe_entry_time": f"{date_str} {entry_time}",
            "pe_exit_price": round(pe_exit_price, 2),
            "pe_exit_time": f"{pe_exit_date_str} {pe_exit_time_str}",
            "pe_exit_reason": pe_exit_reason,
            "pe_stopped": pe_exit_reason == "STOP_LOSS",
            "pe_pnl": round(pe_pnl, 2),
            "total_pnl": round(total_pnl, 2)
        }
        
        results.append(result)
        print(f"  Exit: CE @ {ce_exit_price} on {ce_exit_date_str} at {ce_exit_time_str} ({ce_exit_reason}), PE @ {pe_exit_price} on {pe_exit_date_str} at {pe_exit_time_str} ({pe_exit_reason}), Total P&L: {total_pnl:.2f}")
        
        # Remember last exit date: no open trade at 15:18 on or after this day
        last_exit_dt = max(
            datetime.strptime(ce_exit_date_str, "%Y-%m-%d"),
            datetime.strptime(pe_exit_date_str, "%Y-%m-%d")
        )
        last_exit_date = last_exit_dt.date()
        # If last leg exited on a day *after* entry day, consider that day for new entry at 15:18
        # If entry and last exit are same day (e.g. enter and exit same day), advance to avoid infinite loop
        if date_str == last_exit_dt.strftime("%Y-%m-%d"):
            current_date = _next_trading_day(last_exit_dt)
        else:
            current_date = last_exit_dt
    
    return results


def compute_summary(results: List[Dict], config: Dict) -> Dict:
    """Compute summary metrics (total_charges, max_drawdown, max_drawdown_days, etc.) for dashboard."""
    if not results:
        return {
            'results': [],
            'total_trading_days': 0,
            'total_trades': 0,
            'total_reentries': 0,
            'total_pnl': 0,
            'total_orders': 0,
            'per_order_charges': 0,
            'total_charges': 0,
            'net_pnl': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'average_pnl': 0,
            'max_profit': 0,
            'max_loss': 0,
            'max_drawdown': 0,
            'max_drawdown_days': 0,
        }
    per_order_charges = config['basic_settings'].get('per_order_charges', 100)
    # 4 orders per trade: CE entry, PE entry, CE exit, PE exit (same as positional/intraday)
    orders_per_trade = 4
    total_trades = len(results)
    unique_dates = set(r.get('date', '') for r in results if r.get('date'))
    total_trading_days = len(unique_dates)
    total_pnl = sum(r['total_pnl'] for r in results)
    total_orders = total_trades * orders_per_trade
    # Match positional/intraday: charges = order tickets × per_order_charges (no lot_multiple)
    total_charges = total_orders * per_order_charges
    net_pnl = total_pnl - total_charges
    winning_trades = sum(1 for r in results if r['total_pnl'] > 0)
    losing_trades = sum(1 for r in results if r['total_pnl'] < 0)
    average_pnl = total_pnl / total_trades if total_trades > 0 else 0
    max_profit = max((r['total_pnl'] for r in results), default=0)
    max_loss = min((r['total_pnl'] for r in results), default=0)
    # Max drawdown and max drawdown days (sorted by date)
    sorted_results = sorted(results, key=lambda r: r.get('date', ''))
    cumulative_pnl = 0
    max_cumulative = 0
    max_drawdown = 0
    current_drawdown_days = 0
    max_drawdown_days = 0
    for r in sorted_results:
        cumulative_pnl += r['total_pnl']
        if cumulative_pnl > max_cumulative:
            max_cumulative = cumulative_pnl
            current_drawdown_days = 0
        else:
            drawdown = max_cumulative - cumulative_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            current_drawdown_days += 1
            max_drawdown_days = max(max_drawdown_days, current_drawdown_days)
    return {
        'results': results,
        'total_trading_days': total_trading_days,
        'total_trades': total_trades,
        'total_reentries': 0,
        'total_pnl': round(total_pnl, 2),
        'total_orders': total_orders,
        'per_order_charges': per_order_charges,
        'total_charges': round(total_charges, 2),
        'net_pnl': round(net_pnl, 2),
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'average_pnl': round(average_pnl, 2),
        'max_profit': round(max_profit, 2),
        'max_loss': round(max_loss, 2),
        'max_drawdown': round(max_drawdown, 2),
        'max_drawdown_days': max_drawdown_days,
    }


def main():
    """Main function"""
    config = load_config()
    
    print("=" * 80)
    print("EOD Backtest (expiry): Enter at 15:18, hold until SL/target or expiry")
    print("=" * 80)
    
    results = run_backtest(config)
    output = compute_summary(results, config)
    
    # Save results as dict (with summary) so dashboard shows total_charges, max_drawdown_days, etc.
    output_file = config['output'].get('results_json', 'backtest_results.json')
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nBacktest complete. Results saved to {output_file}")
    print(f"Total trades: {len(results)}")
    
    if results:
        total_pnl = output['total_pnl']
        total_charges = output['total_charges']
        max_drawdown_days = output['max_drawdown_days']
        winning_trades = output['winning_trades']
        losing_trades = output['losing_trades']
        print(f"Total P&L: {total_pnl:.2f}")
        print(f"Total charges: {total_charges:.2f}")
        print(f"Net P&L: {output['net_pnl']:.2f}")
        print(f"Max drawdown: {output['max_drawdown']:.2f}")
        print(f"Max drawdown days: {max_drawdown_days}")
        print(f"Winning trades: {winning_trades}")
        print(f"Losing trades: {losing_trades}")
        if winning_trades + losing_trades > 0:
            win_rate = (winning_trades / (winning_trades + losing_trades)) * 100
            print(f"Win rate: {win_rate:.2f}%")


if __name__ == "__main__":
    main()
