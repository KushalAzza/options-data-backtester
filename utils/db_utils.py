#!/usr/bin/env python3
"""
Database utilities for storing backtest history
"""

import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Optional


DB_FILE = "backtest_history.db"


def init_database():
    """Initialize the database and create tables if they don't exist"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backtest_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            config_data TEXT NOT NULL,
            summary_data TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()


def save_backtest_history(config: Dict, summary: Dict) -> int:
    """
    Save backtest configuration and summary to database
    Returns the ID of the inserted record
    """
    init_database()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    config_json = json.dumps(config)
    summary_json = json.dumps(summary)
    
    cursor.execute('''
        INSERT INTO backtest_history (config_data, summary_data)
        VALUES (?, ?)
    ''', (config_json, summary_json))
    
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return record_id


def get_all_backtest_history() -> List[Dict]:
    """Get all backtest history records"""
    init_database()
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, created_at, config_data, summary_data
        FROM backtest_history
        ORDER BY created_at DESC
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    history = []
    for row in rows:
        try:
            config = json.loads(row['config_data']) if row['config_data'] else {}
            summary = json.loads(row['summary_data']) if row['summary_data'] else {}
            
            history.append({
                'id': row['id'],
                'created_at': row['created_at'],
                'config': config,
                'summary': summary
            })
        except (json.JSONDecodeError, ValueError) as e:
            # Skip corrupted records and log the error
            print(f"Warning: Skipping corrupted record ID {row['id']}: {e}")
            continue
    
    return history


def get_backtest_by_id(record_id: int) -> Optional[Dict]:
    """Get a specific backtest record by ID"""
    init_database()
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, created_at, config_data, summary_data
        FROM backtest_history
        WHERE id = ?
    ''', (record_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        try:
            config = json.loads(row['config_data']) if row['config_data'] else {}
            summary = json.loads(row['summary_data']) if row['summary_data'] else {}
            
            return {
                'id': row['id'],
                'created_at': row['created_at'],
                'config': config,
                'summary': summary
            }
        except (json.JSONDecodeError, ValueError) as e:
            # Return None if JSON is corrupted
            print(f"Error: Corrupted record ID {row['id']}: {e}")
            return None
    
    return None


def delete_backtest_record(record_id: int) -> bool:
    """Delete a backtest record by ID. Returns True if deleted, False if not found"""
    init_database()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM backtest_history
        WHERE id = ?
    ''', (record_id,))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted
