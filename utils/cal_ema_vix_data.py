#!/usr/bin/env python3
"""
Script to add base_ema (20-day EMA) values to india_vix_intraday_price.json
EMA is calculated using daily open prices (1-day intervals), then applied to all minute entries.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os


def load_vix_data(file_path: str) -> Dict:
    """Load VIX intraday data"""
    print(f"Loading VIX data from {file_path}...")
    with open(file_path, 'r') as f:
        return json.load(f)


def save_vix_data(file_path: str, data: Dict):
    """Save VIX intraday data"""
    print(f"Saving VIX data to {file_path}...")
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)


def calculate_ema_series(opens: List[float], period: int) -> List[Optional[float]]:
    """
    Calculate EMA for a series of open prices.
    Returns list of EMA values (None for first period-1 values).
    """
    if len(opens) < period:
        return [None] * len(opens)
    
    ema_values = []
    multiplier = 2.0 / (period + 1)
    
    # First EMA value is SMA of first 'period' values
    sma = sum(opens[:period]) / period
    
    # Pad with None for first period-1 values
    ema_values = [None] * (period - 1)
    ema_values.append(sma)
    
    # Calculate EMA for remaining values
    for i in range(period, len(opens)):
        ema = (opens[i] - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)
    
    return ema_values


def add_base_ema_to_vix_data(vix_data: Dict, period: int = 20) -> Dict:
    """
    Add base_ema (20-day EMA) to each entry in vix_data.
    EMA is calculated using daily open prices (1-day intervals), then applied to all minute entries.
    """
    # Get sorted dates
    dates = sorted(vix_data.keys())
    
    if not dates:
        return vix_data
    
    print(f"Processing {len(dates)} dates...")
    print(f"EMA period: {period} days")
    
    # Build daily candles - get the first open price of each day
    daily_opens = []
    date_to_daily_open = {}
    
    for date in dates:
        entries = vix_data[date]
        if entries:
            # Get the first entry's open price as the daily open (fallback to close if open not available)
            first_entry = entries[0]
            daily_open = first_entry.get('open', first_entry.get('close'))
            daily_opens.append(daily_open)
            date_to_daily_open[date] = daily_open
        else:
            daily_opens.append(None)
            date_to_daily_open[date] = None
    
    print(f"Total daily opens: {len(daily_opens)}")
    
    # Filter out None values for EMA calculation, but keep track of indices
    valid_daily_opens = []
    valid_date_indices = []
    for i, open_price in enumerate(daily_opens):
        if open_price is not None:
            valid_daily_opens.append(open_price)
            valid_date_indices.append(i)
    
    if len(valid_daily_opens) < period:
        print(f"Warning: Only {len(valid_daily_opens)} valid daily opens, need {period} for EMA calculation")
        # Still process, but EMA will be None for most dates
    
    # Calculate EMA for valid daily opens
    ema_values = calculate_ema_series(valid_daily_opens, period)
    
    # Map EMA values back to dates
    date_to_ema = {}
    for idx, date_idx in enumerate(valid_date_indices):
        date = dates[date_idx]
        if idx < len(ema_values):
            date_to_ema[date] = ema_values[idx] if idx < len(ema_values) else None
        else:
            date_to_ema[date] = None
    
    # Fill in None values for dates that don't have valid opens
    for i, date in enumerate(dates):
        if date not in date_to_ema:
            date_to_ema[date] = None
    
    # Add base_ema to all minute entries for each date
    processed_dates = 0
    for date in dates:
        entries = vix_data[date]
        daily_ema = date_to_ema.get(date)
        
        for entry in entries:
            entry['base_ema'] = round(daily_ema, 2) if daily_ema is not None else None
        
        processed_dates += 1
        if processed_dates % 100 == 0:
            print(f"  Processed {processed_dates}/{len(dates)} dates...")
    
    print(f"  Processed {processed_dates}/{len(dates)} dates... Done!")
    return vix_data


def main():
    print("=" * 60)
    print("Add Base EMA (20-day) to India VIX Intraday Price Data")
    print("=" * 60)
    
    vix_file = "data/india_vix_intraday_price.json"
    ema_period = 20  # 20 days
    
    if not os.path.exists(vix_file):
        print(f"Error: VIX data file not found: {vix_file}")
        return
    
    print(f"\nConfiguration:")
    print(f"  VIX data file: {vix_file}")
    print(f"  EMA period: {ema_period} days (1-day intervals)")
    print()
    
    # Load data
    vix_data = load_vix_data(vix_file)
    dates = sorted(vix_data.keys())
    print(f"  Loaded {len(dates)} dates")
    if dates:
        print(f"  Date range: {dates[0]} to {dates[-1]}")
    
    # Add EMA values
    print("\nCalculating and adding base_ema values (20-day EMA on daily intervals)...")
    vix_data = add_base_ema_to_vix_data(vix_data, ema_period)
    
    # Save data
    print("\nSaving updated VIX data...")
    save_vix_data(vix_file, vix_data)
    print(f"  Saved to {vix_file}")
    
    # Verify
    print("\nVerification:")
    if dates:
        # Check first date with EMA values
        for i, date in enumerate(dates):
            entries = vix_data[date]
            has_ema = any(e.get('base_ema') is not None for e in entries)
            if has_ema:
                print(f"  First date with EMA: {date}")
                # Find first entry with EMA
                for entry in entries:
                    if entry.get('base_ema') is not None:
                        print(f"  First entry with EMA: {entry['time']}")
                        print(f"    open: {entry.get('open', entry.get('close', 'N/A'))}")
                        print(f"    base_ema: {entry['base_ema']}")
                        break
                break
        
        # Check last date
        last_date = dates[-1]
        last_entries = vix_data[last_date]
        if last_entries:
            last_entry = last_entries[-1]
            print(f"  Last entry: {last_entry['time']}")
            print(f"    open: {last_entry.get('open', last_entry.get('close', 'N/A'))}")
            print(f"    base_ema: {last_entry.get('base_ema')}")
        
        # Show a sample of dates with EMA values
        print(f"\n  Sample dates with EMA values:")
        sample_count = 0
        for date in dates:
            entries = vix_data[date]
            if entries and entries[0].get('base_ema') is not None:
                first_open = entries[0].get('open', entries[0].get('close', 'N/A'))
                print(f"    {date}: EMA = {entries[0]['base_ema']}, Open = {first_open}")
                sample_count += 1
                if sample_count >= 5:
                    break
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
