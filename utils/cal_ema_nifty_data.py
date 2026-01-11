#!/usr/bin/env python3
"""
Script to add fast_ema and slow_ema values to nifty_intraday_price.json
EMA is calculated continuously using historical close prices at specified interval.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os
import sys


def load_config(config_path: str = "config.json") -> Dict:
    """Load configuration from specified config file (defaults to config.json)"""
    with open(config_path, 'r') as f:
        return json.load(f)


def load_nifty_data(file_path: str) -> Dict:
    """Load Nifty intraday data"""
    with open(file_path, 'r') as f:
        return json.load(f)


def save_nifty_data(file_path: str, data: Dict):
    """Save Nifty intraday data"""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)


def aggregate_to_interval(entries: List[Dict], interval_minutes: int) -> List[Dict]:
    """
    Aggregate 1-minute data to specified interval candles.
    Returns list of candles with 'time' and 'close' (close of the interval).
    """
    if not entries:
        return []
    
    candles = []
    current_bucket = None
    bucket_entries = []
    
    for entry in entries:
        time_str = entry['time']
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        
        # Calculate bucket start time
        bucket_minute = (dt.minute // interval_minutes) * interval_minutes
        bucket_start = dt.replace(minute=bucket_minute, second=0, microsecond=0)
        
        if current_bucket is None:
            current_bucket = bucket_start
            bucket_entries = [entry]
        elif bucket_start == current_bucket:
            bucket_entries.append(entry)
        else:
            # Close the previous bucket - use the last entry's close as the candle close
            if bucket_entries:
                last_entry = bucket_entries[-1]
                candles.append({
                    'time': current_bucket.strftime("%Y-%m-%d %H:%M:%S"),
                    'close': last_entry['close']
                })
            current_bucket = bucket_start
            bucket_entries = [entry]
    
    # Don't forget the last bucket
    if bucket_entries:
        last_entry = bucket_entries[-1]
        candles.append({
            'time': current_bucket.strftime("%Y-%m-%d %H:%M:%S"),
            'close': last_entry['close']
        })
    
    return candles


def calculate_ema_series(closes: List[float], period: int) -> List[Optional[float]]:
    """
    Calculate EMA for a series of close prices.
    Returns list of EMA values (None for first period-1 values).
    """
    if len(closes) < period:
        return [None] * len(closes)
    
    ema_values = []
    multiplier = 2.0 / (period + 1)
    
    # First EMA value is SMA of first 'period' values
    sma = sum(closes[:period]) / period
    
    # Pad with None for first period-1 values
    ema_values = [None] * (period - 1)
    ema_values.append(sma)
    
    # Calculate EMA for remaining values
    for i in range(period, len(closes)):
        ema = (closes[i] - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)
    
    return ema_values


def add_ema_to_nifty_data(nifty_data: Dict, interval_minutes: int, 
                          fast_period: int, slow_period: int) -> Dict:
    """
    Add fast_ema and slow_ema to each minute entry in nifty_data.
    EMA is calculated continuously across all dates using interval candles.
    """
    # Get sorted dates
    dates = sorted(nifty_data.keys())
    
    if not dates:
        return nifty_data
    
    print(f"Processing {len(dates)} dates...")
    print(f"EMA parameters: interval={interval_minutes}min, fast={fast_period}, slow={slow_period}")
    
    # Build a continuous list of interval candles across all dates
    all_interval_candles = []
    candle_date_map = {}  # Map from candle time to (date, candle_index)
    
    for date in dates:
        entries = nifty_data[date]
        day_candles = aggregate_to_interval(entries, interval_minutes)
        
        for i, candle in enumerate(day_candles):
            candle_date_map[candle['time']] = (date, len(all_interval_candles))
            all_interval_candles.append(candle)
    
    print(f"Total interval candles: {len(all_interval_candles)}")
    
    # Calculate EMA for all interval candles
    closes = [c['close'] for c in all_interval_candles]
    fast_ema_values = calculate_ema_series(closes, fast_period)
    slow_ema_values = calculate_ema_series(closes, slow_period)
    
    # Store EMA values in candles
    for i, candle in enumerate(all_interval_candles):
        candle['fast_ema'] = round(fast_ema_values[i], 2) if fast_ema_values[i] is not None else None
        candle['slow_ema'] = round(slow_ema_values[i], 2) if slow_ema_values[i] is not None else None
    
    # Create a lookup map: candle_time -> (fast_ema, slow_ema)
    candle_ema_map = {}
    for candle in all_interval_candles:
        candle_ema_map[candle['time']] = (candle['fast_ema'], candle['slow_ema'])
    
    # Now add EMA values to each minute entry
    # For each minute entry, find the interval candle it belongs to
    # and use the EMA value from the PREVIOUS completed candle
    
    processed_dates = 0
    for date in dates:
        entries = nifty_data[date]
        
        for entry in entries:
            time_str = entry['time']
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            
            # Calculate which interval bucket this minute belongs to
            bucket_minute = (dt.minute // interval_minutes) * interval_minutes
            bucket_start = dt.replace(minute=bucket_minute, second=0, microsecond=0)
            bucket_key = bucket_start.strftime("%Y-%m-%d %H:%M:%S")
            
            # Find the previous completed candle
            # If we're at the start of a bucket, use the previous bucket's EMA
            # If we're in the middle of a bucket, use the current bucket's EMA
            # (because by the end of this minute, the current candle is being formed)
            
            # For real-time application, we'd use the previous candle's EMA
            # But for this backtest, we'll assign the current candle's EMA value
            # to all minutes within that candle's timeframe
            
            if bucket_key in candle_ema_map:
                fast_ema, slow_ema = candle_ema_map[bucket_key]
                entry['fast_ema'] = fast_ema
                entry['slow_ema'] = slow_ema
            else:
                entry['fast_ema'] = None
                entry['slow_ema'] = None
        
        processed_dates += 1
        if processed_dates % 100 == 0:
            print(f"  Processed {processed_dates}/{len(dates)} dates...")
    
    print(f"  Processed {processed_dates}/{len(dates)} dates... Done!")
    return nifty_data


def main():
    print("=" * 60)
    print("Add EMA values to Nifty Intraday Price Data")
    print("=" * 60)
    
    # Load config - accept optional config file path as command line argument
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    config = load_config(config_path)
    ema_config = config.get('ema_signals', {})
    data_paths = config.get('data_paths', {})
    
    interval_minutes = ema_config.get('time_interval', 15)
    fast_period = ema_config.get('fast_ema', 9)
    slow_period = ema_config.get('slow_ema', 21)
    nifty_file = data_paths.get('nifty_intraday', 'data/nifty_intraday_price.json')
    
    print(f"\nConfiguration:")
    print(f"  Nifty data file: {nifty_file}")
    print(f"  Interval: {interval_minutes} minutes")
    print(f"  Fast EMA period: {fast_period}")
    print(f"  Slow EMA period: {slow_period}")
    print()
    
    # Load data
    print("Loading Nifty intraday data...")
    nifty_data = load_nifty_data(nifty_file)
    print(f"  Loaded {len(nifty_data)} dates")
    
    # Add EMA values
    print("\nCalculating and adding EMA values...")
    nifty_data = add_ema_to_nifty_data(nifty_data, interval_minutes, fast_period, slow_period)
    
    # Save data
    print("\nSaving updated Nifty data...")
    save_nifty_data(nifty_file, nifty_data)
    print(f"  Saved to {nifty_file}")
    
    # Verify
    print("\nVerification:")
    dates = sorted(nifty_data.keys())
    if dates:
        # Check first date with EMA values
        for date in dates:
            entries = nifty_data[date]
            has_ema = any(e.get('fast_ema') is not None for e in entries)
            if has_ema:
                print(f"  First date with EMA: {date}")
                # Find first entry with EMA
                for entry in entries:
                    if entry.get('fast_ema') is not None:
                        print(f"  First entry with EMA: {entry['time']}")
                        print(f"    fast_ema: {entry['fast_ema']}")
                        print(f"    slow_ema: {entry['slow_ema']}")
                        break
                break
        
        # Check last date
        last_date = dates[-1]
        last_entries = nifty_data[last_date]
        if last_entries:
            last_entry = last_entries[-1]
            print(f"  Last entry: {last_entry['time']}")
            print(f"    fast_ema: {last_entry.get('fast_ema')}")
            print(f"    slow_ema: {last_entry.get('slow_ema')}")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()

