# This is a Python 3 script for a mod manager application for Conan Exiles.
# It uses PySide6 for the GUI and SQLite for local data storage.
# It was developed with the help of DeepSeek AI.

import os
import sys
import json
import sqlite3
import requests
import threading
import webbrowser
from datetime import datetime, timedelta
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import pickle

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QLineEdit,
    QTreeWidget, QTreeWidgetItem, QComboBox, QCheckBox, QMessageBox,
    QTabWidget, QGroupBox, QTextEdit, QTextBrowser, QSplitter, QProgressBar,
    QFileDialog, QMenu, QInputDialog, QHeaderView, QDialog, QTableWidget,
    QTableWidgetItem, QRadioButton, QButtonGroup
)
from PySide6.QtCore import Qt, QTimer, Signal as pyqtSignal, QThread, QModelIndex
from PySide6.QtGui import QAction, QIcon, QFont, QColor, QBrush

# Constants
APP_ID = 440900   # This is the Conan Exiles Steam App ID
DATABASE_FILE = "ce_mm.db"
CACHE_FILE = "mod_cache.pkl"
CACHE_EXPIRY_HOURS = 6
STEAM_API_BASE = "https://api.steampowered.com"

# ==================== DATABASE MODULE ====================

class Database:
    def __init__(self, db_file=DATABASE_FILE):
        self.db_file = db_file
        self.init_database()
   
    def get_connection(self):
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn
   
    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()
       
        # Mods table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mods (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                creator TEXT,
                tags TEXT,
                subscriptions INTEGER,
                preview_url TEXT,
                time_updated INTEGER,
                time_fetched TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                category TEXT,
                load_order_notes TEXT
            )
        ''')
       
        # Favorites table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                mod_id TEXT PRIMARY KEY,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (mod_id) REFERENCES mods(id) ON DELETE CASCADE
            )
        ''')
       
        # Load order rules table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS load_order_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mod_id TEXT,
                rule_type TEXT CHECK(rule_type IN ('requires', 'conflicts_with', 'place_before', 'place_after', 'priority')),
                target_mod_id TEXT,
                priority INTEGER DEFAULT 50,
                source TEXT DEFAULT 'user',
                notes TEXT,
                FOREIGN KEY (mod_id) REFERENCES mods(id),
                FOREIGN KEY (target_mod_id) REFERENCES mods(id)
            )
        ''')
       
        # Load order presets table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS load_order_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                mod_ids TEXT NOT NULL,  -- JSON array of mod IDs in order
                created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_used TIMESTAMP,
                is_default INTEGER DEFAULT 0
            )
        ''')
       
        # Mod categories (for user-defined categorization)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mod_categories (
                mod_id TEXT,
                category TEXT,
                PRIMARY KEY (mod_id, category)
            )
        ''')
       
        # Settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
       
        # Insert default settings if they don't exist
        default_settings = [
            ('steam_api_key', ''),
            ('auto_update_interval', '24'),  # hours
            ('default_load_order_style', 'optimized'),
            ('last_update_check', ''),
            ('conan_install_path', ''),
        ]
       
        for key, value in default_settings:
            cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
       
        conn.commit()
        conn.close()
   
    def save_mod(self, mod_data):
        conn = self.get_connection()
        cursor = conn.cursor()
       
        cursor.execute('''
            INSERT OR REPLACE INTO mods
            (id, title, description, creator, tags, subscriptions, preview_url, time_updated, time_fetched)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (
            mod_data['id'],
            mod_data.get('title', ''),
            mod_data.get('description', ''),
            mod_data.get('creator', ''),
            json.dumps(mod_data.get('tags', [])),
            mod_data.get('subscriptions', 0),
            mod_data.get('preview_url', ''),
            mod_data.get('time_updated', 0)
        ))
       
        conn.commit()
        conn.close()
   
    def get_all_mods(self):
        conn = self.get_connection()
        cursor = conn.cursor()
       
        cursor.execute('''
            SELECT m.*,
                   CASE WHEN f.mod_id IS NOT NULL THEN 1 ELSE 0 END as is_favorite,
                   GROUP_CONCAT(mc.category) as user_categories
            FROM mods m
            LEFT JOIN favorites f ON m.id = f.mod_id
            LEFT JOIN mod_categories mc ON m.id = mc.mod_id
            GROUP BY m.id
            ORDER BY m.title COLLATE NOCASE
        ''')
       
        mods = []
        for row in cursor.fetchall():
            mod = dict(row)
            mod['tags'] = json.loads(mod['tags']) if mod['tags'] else []
            mod['is_favorite'] = bool(mod['is_favorite'])
            mod['user_categories'] = mod['user_categories'].split(',') if mod['user_categories'] else []
            mods.append(mod)
       
        conn.close()
        return mods
   
    def get_favorite_mods(self):
        conn = self.get_connection()
        cursor = conn.cursor()
       
        cursor.execute('''
            SELECT m.*, 1 as is_favorite,
                   GROUP_CONCAT(mc.category) as user_categories
            FROM mods m
            JOIN favorites f ON m.id = f.mod_id
            LEFT JOIN mod_categories mc ON m.id = mc.mod_id
            GROUP BY m.id
            ORDER BY f.added_date DESC
        ''')
       
        mods = []
        for row in cursor.fetchall():
            mod = dict(row)
            mod['tags'] = json.loads(mod['tags']) if mod['tags'] else []
            mod['is_favorite'] = True
            mod['user_categories'] = mod['user_categories'].split(',') if mod['user_categories'] else []
            mods.append(mod)
       
        conn.close()
        return mods
   
    def add_favorite(self, mod_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO favorites (mod_id) VALUES (?)', (mod_id,))
        conn.commit()
        conn.close()
   
    def remove_favorite(self, mod_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM favorites WHERE mod_id = ?', (mod_id,))
        conn.commit()
        conn.close()
   
    def save_load_order_preset(self, name, mod_ids, is_default=False):
        conn = self.get_connection()
        cursor = conn.cursor()
       
        # Clear default flag if this is being set as default
        if is_default:
            cursor.execute('UPDATE load_order_presets SET is_default = 0')
       
        cursor.execute('''
            INSERT OR REPLACE INTO load_order_presets (name, mod_ids, is_default, last_used)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ''', (name, json.dumps(mod_ids), 1 if is_default else 0))
       
        conn.commit()
        conn.close()
   
    def get_load_order_presets(self):
        conn = self.get_connection()
        cursor = conn.cursor()
       
        cursor.execute('SELECT * FROM load_order_presets ORDER BY last_used DESC')
        presets = []
        for row in cursor.fetchall():
            preset = dict(row)
            preset['mod_ids'] = json.loads(preset['mod_ids'])
            presets.append(preset)
       
        conn.close()
        return presets
   
    def delete_load_order_preset(self, preset_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM load_order_presets WHERE id = ?', (preset_id,))
        conn.commit()
        conn.close()
   
    def save_setting(self, key, value):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
        conn.close()
   
    def get_setting(self, key, default=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else default

# ==================== STEAM API MODULE ====================

class SteamAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = STEAM_API_BASE
   
    def fetch_mods(self, app_id=APP_ID, max_results=500):
        """Fetch mods from Steam Workshop"""
        if not self.api_key:
            raise ValueError("Steam API key not set")
       
        all_mods = []
        cursor = "*"
       
        try:
            while len(all_mods) < max_results:
                # QueryFiles endpoint
                url = f"{self.base_url}/IPublishedFileService/QueryFiles/v1/"
                # Do not restrict by creator_appid or file type here — request all items for the app.
                params = {
                    'key': self.api_key,
                    'appid': app_id,
                    # Leave query_type unset or 0 to broaden results (do not restrict to creator_appid)
                    'cursor': cursor,
                    'numperpage': 100,  # Max per page
                    'return_tags': True,
                    'return_details': True,
                    'return_children': True,
                    'return_short_description': True,
                    'return_for_sale_data': False,
                    'return_metadata': True,
                    'return_previews': True,
                }
               
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
               
                mods = data.get('response', {}).get('publishedfiledetails', [])
               
                # Collect page mods and then enrich with full details
                page_mods = []
                page_ids = []
                for mod in mods:
                    if mod.get('result', 0) != 1:
                        continue

                    # Accept both 'file_type' and 'filetype' keys and include all returned items.
                    mod_id = str(mod.get('publishedfileid', ''))
                    page_ids.append(mod_id)
                    page_mods.append({
                        'id': mod_id,
                        'title': mod.get('title', 'Unknown'),
                        'description': mod.get('file_description', '') or mod.get('description', ''),
                        'creator': mod.get('creator', ''),
                        'tags': [tag.get('tag', '') for tag in mod.get('tags', [])],
                        'subscriptions': mod.get('subscriptions', 0),
                        'preview_url': mod.get('preview_url', ''),
                        'time_updated': mod.get('time_updated', 0),
                        'time_created': mod.get('time_created', 0),
                        'raw_filetype': mod.get('file_type', mod.get('filetype')),
                    })

                # Enrich page mods with full details using GetPublishedFileDetails
                try:
                    if page_ids:
                        details = self.get_mod_details(page_ids)
                        detail_map = {d.get('id'): d for d in details}
                        for pm in page_mods:
                            d = detail_map.get(pm['id'])
                            if d:
                                # Overwrite with full fields when present
                                for k in ['description', 'time_created', 'time_updated', 'file_size', 'favorites', 'creator_name', 'creator']:
                                    if k in d and d[k] is not None:
                                        pm[k] = d[k]
                except Exception:
                    pass

                all_mods.extend(page_mods)
               
                # Check for more pages
                cursor = data.get('response', {}).get('next_cursor')
                if not cursor:
                    break
               
                # Be nice to Steam's servers
                import time
                time.sleep(0.5)
               
        except Exception as e:
            print(f"Error fetching mods: {e}")
       
        return all_mods
   
    def get_mod_details(self, mod_ids):
        """Get detailed information for specific mods.

        Calls GetPublishedFileDetails and enriches results with creator persona names
        via GetPlayerSummaries when possible.
        """
        if not mod_ids:
            return []

        try:
            # GetPublishedFileDetails endpoint
            url = f"{self.base_url}/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

            data = {'itemcount': len(mod_ids)}
            for i, mod_id in enumerate(mod_ids):
                data[f'publishedfileids[{i}]'] = mod_id

            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            resp_json = response.json()

            mods_details = []
            creator_ids = set()

            for mod in resp_json.get('response', {}).get('publishedfiledetails', []):
                if mod.get('result', 0) != 1:
                    continue

                d = {
                    'id': str(mod.get('publishedfileid', '')),
                    'title': mod.get('title', ''),
                    'description': mod.get('file_description', '') or mod.get('description', ''),
                    'creator': str(mod.get('creator', '')),
                    'time_created': mod.get('time_created') or mod.get('timecreated'),
                    'time_updated': mod.get('time_updated') or mod.get('timeupdated'),
                    'file_size': mod.get('file_size') or mod.get('file_size_bytes') or None,
                    'subscriptions': mod.get('subscriptions', 0),
                    'favorites': mod.get('favorited') or mod.get('favorites') or mod.get('num_favorites') or None,
                    'preview_url': mod.get('preview_url') or None,
                }

                mods_details.append(d)
                if d['creator']:
                    creator_ids.add(d['creator'])

            # Fetch creator persona names if we have creators and an API key
            if creator_ids and self.api_key:
                try:
                    url2 = f"{self.base_url}/ISteamUser/GetPlayerSummaries/v2/"
                    params = {'key': self.api_key, 'steamids': ','.join(creator_ids)}
                    resp2 = requests.get(url2, params=params, timeout=15)
                    resp2.raise_for_status()
                    players = resp2.json().get('response', {}).get('players', [])
                    id_to_name = {p.get('steamid'): p.get('personaname') for p in players}
                    for d in mods_details:
                        d['creator_name'] = id_to_name.get(d['creator'], d['creator'])
                except Exception:
                    for d in mods_details:
                        d['creator_name'] = d.get('creator')

            return mods_details

        except Exception as e:
            print(f"Error fetching mod details: {e}")
            return []

# ==================== LOAD ORDER ENGINE ====================

class LoadOrderCategory(Enum):
    FRAMEWORK = 100
    ADMIN_TOOLS = 90
    CORE_OVERRIDES = 80
    GAMEPLAY = 70
    BUILDING = 60
    ITEMS = 50
    CHARACTERS = 40
    UI = 30
    LIBRARY = 20
    DECORATION = 10

class ModRule:
    def __init__(self, mod_id, rule_type, target_mod_id=None, priority=None, notes=""):
        self.mod_id = mod_id
        self.rule_type = rule_type  # requires, conflicts_with, place_before, place_after
        self.target_mod_id = target_mod_id
        self.priority = priority
        self.notes = notes

class LoadOrderEngine:
    """Engine for creating optimized load orders based on mod rules and categories"""
   
    # Known framework and library mods (partial list)
    FRAMEWORK_MODS = {
        '880454836': 'Pippi',  # Pippi - User & Server Management
        '1625650704': 'ModControlPanel',
    }
   
    LIBRARY_MODS = {
        '2679653448': 'LBPR - Additional Features',
        '2291760550': 'Kerozards Paragon Leveling',
    }
   
    # Known mod categories based on common tags
    CATEGORY_KEYWORDS = {
        LoadOrderCategory.FRAMEWORK: ['pippi', 'framework', 'admin'],
        LoadOrderCategory.ADMIN_TOOLS: ['admin', 'manager', 'control'],
        LoadOrderCategory.CORE_OVERRIDES: ['overhaul', 'core', 'savage', 'age'],
        LoadOrderCategory.GAMEPLAY: ['gameplay', 'survival', 'combat', 'thrall'],
        LoadOrderCategory.BUILDING: ['building', 'construction', 'architect'],
        LoadOrderCategory.ITEMS: ['weapon', 'armor', 'item', 'equipment'],
        LoadOrderCategory.CHARACTERS: ['character', 'race', 'appearance'],
        LoadOrderCategory.UI: ['ui', 'interface', 'hud', 'inventory'],
        LoadOrderCategory.LIBRARY: ['library', 'prerequisite', 'dependency'],
        LoadOrderCategory.DECORATION: ['decoration', 'decor', 'furniture'],
    }
   
    def __init__(self, database):
        self.db = database
        self.rules = []
        self.load_rules()
   
    def load_rules(self):
        """Load rules from database"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM load_order_rules')
       
        for row in cursor.fetchall():
            rule = ModRule(
                mod_id=row['mod_id'],
                rule_type=row['rule_type'],
                target_mod_id=row['target_mod_id'],
                priority=row['priority'],
                notes=row['notes']
            )
            self.rules.append(rule)
       
        conn.close()
   
    def categorize_mod(self, mod_data):
        """Determine the category of a mod based on its title, tags, and description"""
        title = mod_data.get('title', '').lower()
        tags = [tag.lower() for tag in mod_data.get('tags', [])]
        description = mod_data.get('description', '').lower()
       
        # Check for known mods first
        mod_id = mod_data.get('id', '')
        if mod_id in self.FRAMEWORK_MODS:
            return LoadOrderCategory.FRAMEWORK
        if mod_id in self.LIBRARY_MODS:
            return LoadOrderCategory.LIBRARY
       
        # Check keywords in title and tags
        text_to_check = f"{title} {' '.join(tags)} {description}"
       
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_to_check:
                    return category
       
        # Default category
        return LoadOrderCategory.GAMEPLAY
   
    def get_mod_priority(self, mod_data):
        """Calculate priority score for a mod"""
        category = self.categorize_mod(mod_data)
        base_priority = category.value
       
        # Adjust based on rules
        mod_id = mod_data.get('id', '')
        for rule in self.rules:
            if rule.mod_id == mod_id and rule.rule_type == 'priority':
                if rule.priority is not None:
                    return rule.priority
       
        # Adjust based on subscriptions (popular mods get slight priority boost)
        subscriptions = mod_data.get('subscriptions', 0)
        if subscriptions > 10000:
            base_priority += 5
        elif subscriptions > 5000:
            base_priority += 3
       
        return base_priority
   
    def check_conflicts(self, mod_ids):
        """Check for conflicts between selected mods"""
        conflicts = []
       
        for rule in self.rules:
            if rule.rule_type == 'conflicts_with' and rule.mod_id in mod_ids and rule.target_mod_id in mod_ids:
                conflicts.append((rule.mod_id, rule.target_mod_id, rule.notes))
       
        return conflicts
   
    def check_dependencies(self, mod_ids):
        """Check for missing dependencies"""
        missing_deps = []
       
        for rule in self.rules:
            if rule.rule_type == 'requires' and rule.mod_id in mod_ids and rule.target_mod_id not in mod_ids:
                missing_deps.append((rule.mod_id, rule.target_mod_id, rule.notes))
       
        return missing_deps
   
    def generate_load_order(self, mod_ids, mod_data_map):
        """
        Generate an optimized load order for the given mods
       
        Algorithm:
        1. Apply absolute priority rules
        2. Apply dependency ordering (requires/place_before/place_after)
        3. Sort by category priority
        4. Apply topological sort for dependencies
        """
        if not mod_ids:
            return []
       
        # Create a map of mod data
        mods = [mod_data_map[mod_id] for mod_id in mod_ids if mod_id in mod_data_map]
       
        # Step 1: Sort by priority (highest first) 
# ==================== LOAD ORDER ENGINE ====================

class LoadOrderCategory(Enum):
    FRAMEWORK = 100
    ADMIN_TOOLS = 90
    CORE_OVERRIDES = 80
    GAMEPLAY = 70
    BUILDING = 60
    ITEMS = 50
    CHARACTERS = 40
    UI = 30
    LIBRARY = 20
    DECORATION = 10

class ModRule:
    def __init__(self, mod_id, rule_type, target_mod_id=None, priority=None, notes=""):
        self.mod_id = mod_id
        self.rule_type = rule_type  # requires, conflicts_with, place_before, place_after
        self.target_mod_id = target_mod_id
        self.priority = priority
        self.notes = notes

class LoadOrderEngine:
    """Engine for creating optimized load orders based on mod rules and categories"""
   
    # Known framework and library mods (partial list)
    FRAMEWORK_MODS = {
        '880454836': 'Pippi',  # Pippi - User & Server Management
        '1625650704': 'ModControlPanel',
    }
   
    LIBRARY_MODS = {
        '2679653448': 'LBPR - Additional Features',
        '2291760550': 'Kerozards Paragon Leveling',
    }
   
    # Known mod categories based on common tags
    CATEGORY_KEYWORDS = {
        LoadOrderCategory.FRAMEWORK: ['pippi', 'framework', 'admin'],
        LoadOrderCategory.ADMIN_TOOLS: ['admin', 'manager', 'control'],
        LoadOrderCategory.CORE_OVERRIDES: ['overhaul', 'core', 'savage', 'age'],
        LoadOrderCategory.GAMEPLAY: ['gameplay', 'survival', 'combat', 'thrall'],
        LoadOrderCategory.BUILDING: ['building', 'construction', 'architect'],
        LoadOrderCategory.ITEMS: ['weapon', 'armor', 'item', 'equipment'],
        LoadOrderCategory.CHARACTERS: ['character', 'race', 'appearance'],
        LoadOrderCategory.UI: ['ui', 'interface', 'hud', 'inventory'],
        LoadOrderCategory.LIBRARY: ['library', 'prerequisite', 'dependency'],
        LoadOrderCategory.DECORATION: ['decoration', 'decor', 'furniture'],
    }
   
    def __init__(self, database):
        self.db = database
        self.rules = []
        self.load_rules()
   
    def load_rules(self):
        """Load rules from database"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM load_order_rules')
       
        for row in cursor.fetchall():
            rule = ModRule(
                mod_id=row['mod_id'],
                rule_type=row['rule_type'],
                target_mod_id=row['target_mod_id'],
                priority=row['priority'],
                notes=row['notes']
            )
            self.rules.append(rule)
       
        conn.close()
   
    def categorize_mod(self, mod_data):
        """Determine the category of a mod based on its title, tags, and description"""
        title = mod_data.get('title', '').lower()
        tags = [tag.lower() for tag in mod_data.get('tags', [])]
        description = mod_data.get('description', '').lower()
       
        # Check for known mods first
        mod_id = mod_data.get('id', '')
        if mod_id in self.FRAMEWORK_MODS:
            return LoadOrderCategory.FRAMEWORK
        if mod_id in self.LIBRARY_MODS:
            return LoadOrderCategory.LIBRARY
       
        # Check keywords in title and tags
        text_to_check = f"{title} {' '.join(tags)} {description}"
       
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_to_check:
                    return category
       
        # Default category
        return LoadOrderCategory.GAMEPLAY
   
    def get_mod_priority(self, mod_data):
        """Calculate priority score for a mod"""
        category = self.categorize_mod(mod_data)
        base_priority = category.value
       
        # Adjust based on rules
        mod_id = mod_data.get('id', '')
        for rule in self.rules:
            if rule.mod_id == mod_id and rule.rule_type == 'priority':
                if rule.priority is not None:
                    return rule.priority
       
        # Adjust based on subscriptions (popular mods get slight priority boost)
        subscriptions = mod_data.get('subscriptions', 0)
        if subscriptions > 10000:
            base_priority += 5
        elif subscriptions > 5000:
            base_priority += 3
       
        return base_priority
   
    def check_conflicts(self, mod_ids):
        """Check for conflicts between selected mods"""
        conflicts = []
       
        for rule in self.rules:
            if rule.rule_type == 'conflicts_with' and rule.mod_id in mod_ids and rule.target_mod_id in mod_ids:
                conflicts.append((rule.mod_id, rule.target_mod_id, rule.notes))
       
        return conflicts
   
    def check_dependencies(self, mod_ids):
        """Check for missing dependencies"""
        missing_deps = []
       
        for rule in self.rules:
            if rule.rule_type == 'requires' and rule.mod_id in mod_ids and rule.target_mod_id not in mod_ids:
                missing_deps.append((rule.mod_id, rule.target_mod_id, rule.notes))
       
        return missing_deps
   
    def generate_load_order(self, mod_ids, mod_data_map):
        """
        Generate an optimized load order for the given mods
       
        Algorithm:
        1. Apply absolute priority rules
        2. Apply dependency ordering (requires/place_before/place_after)
        3. Sort by category priority
        4. Apply topological sort for dependencies
        """
        if not mod_ids:
            return []
       
        # Create a map of mod data
        mods = [mod_data_map[mod_id] for mod_id in mod_ids if mod_id in mod_data_map]
       
        # Step 1: Sort by priority (highest first)
        mods.sort(key=lambda x: self.get_mod_priority(x), reverse=True)
       
        # Step 2: Apply explicit ordering rules
        ordered_mods = self.apply_ordering_rules(mods)
       
        # Step 3: Extract IDs in final order
        load_order = [mod['id'] for mod in ordered_mods]
       
        return load_order
   
    def apply_ordering_rules(self, mods):
        """Apply ordering rules to the mod list"""
        # Start with the priority-sorted list
        ordered = mods.copy()
       
        # Apply place_before and place_after rules
        for rule in self.rules:
            if rule.rule_type in ['place_before', 'place_after']:
                self.apply_single_rule(ordered, rule)
       
        return ordered
   
    def apply_single_rule(self, mods, rule):
        """Apply a single ordering rule to the mod list"""
        mod_ids = [mod['id'] for mod in mods]
       
        if rule.mod_id not in mod_ids or not rule.target_mod_id or rule.target_mod_id not in mod_ids:
            return
       
        mod_idx = mod_ids.index(rule.mod_id)
        target_idx = mod_ids.index(rule.target_mod_id)
       
        if rule.rule_type == 'place_before':
            # Move mod before target
            if mod_idx > target_idx:
                mod = mods.pop(mod_idx)
                # Insert before target (which may have moved after pop)
                new_target_idx = mod_ids.index(rule.target_mod_id)
                mods.insert(new_target_idx, mod)
       
        elif rule.rule_type == 'place_after':
            # Move mod after target
            if mod_idx < target_idx:
                mod = mods.pop(mod_idx)
                # Insert after target
                new_target_idx = mod_ids.index(rule.target_mod_id)
                mods.insert(new_target_idx + 1, mod)

 # ==================== GUI COMPONENTS ====================

class ModListWidget(QListWidget):
    """Custom list widget for displaying mods"""
   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
   
    def add_mod_item(self, mod_data, is_favorite=False):
        item = QListWidgetItem(mod_data['title'])
        item.setData(Qt.ItemDataRole.UserRole, mod_data['id'])
       
        # Add tooltip with mod info
        tooltip = f"ID: {mod_data['id']}\n"
        tooltip += f"Creator: {mod_data.get('creator', 'Unknown')}\n"
        tooltip += f"Subscribers: {mod_data.get('subscriptions', 0):,}\n"
        if mod_data.get('tags'):
            tooltip += f"Tags: {', '.join(mod_data['tags'][:5])}"
        item.setToolTip(tooltip)
       
        # Highlight favorites (take precedence)
        if is_favorite:
            item.setForeground(QColor(255, 140, 0))  # Orange
        else:
            # Color collections differently (if indicated)
            rt = mod_data.get('raw_filetype') or mod_data.get('file_type') or mod_data.get('filetype')
            if rt is not None and str(rt) == '2':
                item.setForeground(QColor(135, 206, 235))  # Light sky blue for collections
       
        self.addItem(item)

class LoadOrderWidget(QListWidget):
    """Widget for displaying and editing load order"""
   
    itemMoved = pyqtSignal()
   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setAlternatingRowColors(True)
        self.model().rowsMoved.connect(self.on_rows_moved)
   
    def on_rows_moved(self):
        self.itemMoved.emit()
   
    def add_mod_item(self, mod_data):
        item = QListWidgetItem(mod_data['title'])
        item.setData(Qt.ItemDataRole.UserRole, mod_data['id'])
        self.addItem(item)
   
    def get_load_order(self):
        """Get mod IDs in current order"""
        order = []
        for i in range(self.count()):
            item = self.item(i)
            order.append(item.data(Qt.ItemDataRole.UserRole))
        return order

class UpdateThread(QThread):
    """Thread for updating mod data in background"""
   
    update_progress = pyqtSignal(int, str)
    update_finished = pyqtSignal(list)
    update_error = pyqtSignal(str)
   
    def __init__(self, steam_api, database):
        super().__init__()
        self.steam_api = steam_api
        self.database = database
        self.running = True
   
    def run(self):
        try:
            self.update_progress.emit(0, "Starting mod update...")
           
            # Fetch mods from Steam
            self.update_progress.emit(10, "Fetching mods from Steam Workshop...")
            mods = self.steam_api.fetch_mods(max_results=1000)
           
            if not mods:
                self.update_error.emit("No mods fetched. Check your API key.")
                return
           
            # Save mods to database
            self.update_progress.emit(50, f"Saving {len(mods)} mods to database...")
           
            for i, mod in enumerate(mods):
                self.database.save_mod(mod)
               
                # Update progress
                if i % 10 == 0:
                    progress = 50 + (i / len(mods) * 40)
                    self.update_progress.emit(int(progress), f"Saving mod {i+1}/{len(mods)}...")
           
            self.update_progress.emit(95, "Update complete!")
            self.update_finished.emit(mods)
           
        except Exception as e:
            self.update_error.emit(str(e))
   
    def stop(self):
        self.running = False

 
# ==================== MAIN WINDOW ====================

class SettingsDialog(QDialog):
    """Dialog for application settings"""
   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(500)
       
        self.init_ui()
        self.load_settings()
   
    def init_ui(self):
        layout = QVBoxLayout()
       
        # Steam API Key
        api_group = QGroupBox("Steam API Settings")
        api_layout = QVBoxLayout()
       
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Enter your Steam Web API key")
        api_layout.addWidget(QLabel("Steam Web API Key:"))
        api_layout.addWidget(self.api_key_edit)
       
        help_label = QLabel(
            '<a href="https://steamcommunity.com/dev/apikey">'
            'Get a free API key from Steam</a>'
        )
        help_label.setOpenExternalLinks(True)
        api_layout.addWidget(help_label)
       
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
       
        # Update settings
        update_group = QGroupBox("Update Settings")
        update_layout = QVBoxLayout()
       
        self.auto_update_check = QCheckBox("Automatically update mod list")
        update_layout.addWidget(self.auto_update_check)
       
        update_layout.addWidget(QLabel("Update interval (hours):"))
        self.update_interval = QComboBox()
        self.update_interval.addItems(["1", "6", "12", "24", "48", "168"])
        update_layout.addWidget(self.update_interval)
       
        update_group.setLayout(update_layout)
        layout.addWidget(update_group)
       
        # Conan Exiles path
        path_group = QGroupBox("Conan Exiles Installation")
        path_layout = QVBoxLayout()
       
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("C:\\Program Files (x86)\\Steam\\steamapps\\common\\Conan Exiles")
        path_layout.addWidget(QLabel("Game installation path:"))
        path_layout.addWidget(self.path_edit)
       
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_path)
        path_layout.addWidget(browse_btn)
       
        path_group.setLayout(path_layout)
        layout.addWidget(path_group)
       
        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
       
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)
       
        layout.addLayout(button_layout)
        self.setLayout(layout)
   
    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Conan Exiles Installation")
        if path:
            self.path_edit.setText(path)
   
    def load_settings(self):
        db = self.parent.database
        self.api_key_edit.setText(db.get_setting('steam_api_key', ''))
        self.update_interval.setCurrentText(db.get_setting('auto_update_interval', '24'))
        self.path_edit.setText(db.get_setting('conan_install_path', ''))
        self.auto_update_check.setChecked(bool(db.get_setting('auto_update_enabled', '1')))
   
    def save_settings(self):
        db = self.parent.database
        db.save_setting('steam_api_key', self.api_key_edit.text())
        db.save_setting('auto_update_interval', self.update_interval.currentText())
        db.save_setting('conan_install_path', self.path_edit.text())
        db.save_setting('auto_update_enabled', '1' if self.auto_update_check.isChecked() else '0')
       
        QMessageBox.information(self, "Settings Saved", "Settings have been saved successfully.")
        self.accept()

class MainWindow(QMainWindow):
    """Main application window"""
   
    def __init__(self):
        super().__init__()
        self.database = Database()
        self.steam_api = None
        self.load_order_engine = LoadOrderEngine(self.database)
        self.mod_data_map = {}  # Map of mod_id -> mod_data
        self.current_load_order = []
       
        self.init_ui()
        self.load_mod_data()
        self.check_for_updates()
       
        # Setup auto-update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.check_for_updates)
        update_interval = int(self.database.get_setting('auto_update_interval', '24')) * 3600000
        self.update_timer.start(update_interval)
   
    def init_ui(self):
        self.setWindowTitle("Conan Exiles Mod Manager")
        self.setGeometry(100, 100, 1200, 800)
       
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
       
        main_layout = QVBoxLayout(central_widget)
       
        # Create tab widget
        self.tab_widget = QTabWidget()
       
        # Create tabs
        self.create_mod_browser_tab()
        self.create_load_order_tab()
        self.create_favorites_tab()
       
        main_layout.addWidget(self.tab_widget)
       
        # Status bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
       
        # Create menu bar
        self.create_menu_bar()
       
        # Apply styles
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                background-color: #353535;
            }
            QTabBar::tab {
                background-color: #444;
                color: #ddd;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #555;
            }
            QListWidget {
                background-color: #3c3c3c;
                color: #ddd;
                border: 1px solid #555;
            }
            QListWidget::item:selected {
                background-color: #555;
            }
            QListWidget::item:hover {
                background-color: #444;
            }
            QPushButton {
                background-color: #555;
                color: #ddd;
                border: 1px solid #666;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #666;
            }
            QPushButton:pressed {
                background-color: #444;
            }
            QLabel {
                color: #ddd;
            }
            QLineEdit, QComboBox {
                background-color: #3c3c3c;
                color: #ddd;
                border: 1px solid #555;
                padding: 3px;
            }
            QGroupBox {
                color: #ddd;
                border: 1px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
   
    def create_menu_bar(self):
        menubar = self.menuBar()
       
        # File menu
        file_menu = menubar.addMenu("File")
       
        update_action = QAction("Update Mod List", self)
        update_action.triggered.connect(self.update_mods)
        file_menu.addAction(update_action)
       
        export_action = QAction("Export Load Order...", self)
        export_action.triggered.connect(self.export_load_order)
        file_menu.addAction(export_action)
       
        file_menu.addSeparator()
       
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
       
        # Settings menu
        settings_menu = menubar.addMenu("Settings")
       
        settings_action = QAction("Application Settings", self)
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)
       
        # Help menu
        help_menu = menubar.addMenu("Help")
       
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
   
    def create_mod_browser_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
       
        # Search and filter section
        filter_layout = QHBoxLayout()
       
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search mods...")
        self.search_edit.textChanged.connect(self.filter_mods)
        filter_layout.addWidget(self.search_edit)
       
        self.category_combo = QComboBox()
        self.category_combo.addItems(["All Categories", "Building", "Weapons", "Armor", "UI", "Framework", "Gameplay"])
        self.category_combo.currentTextChanged.connect(self.filter_mods)
        filter_layout.addWidget(QLabel("Category:"))
        filter_layout.addWidget(self.category_combo)

        # Option to include or hide collection-type workshop items
        self.show_collections_check = QCheckBox("Show Collections")
        self.show_collections_check.setChecked(False)
        self.show_collections_check.toggled.connect(self.filter_mods)
        filter_layout.addWidget(self.show_collections_check)
       
        layout.addLayout(filter_layout)
       
        # Splitter for mod list and details
        splitter = QSplitter(Qt.Orientation.Horizontal)
       
        # Mod list
        mod_list_widget = QWidget()
        mod_list_layout = QVBoxLayout(mod_list_widget)
       
        mod_list_layout.addWidget(QLabel("Available Mods:"))
       
        self.mod_list = ModListWidget()
        self.mod_list.itemDoubleClicked.connect(self.on_mod_double_clicked)
        mod_list_layout.addWidget(self.mod_list)
       
        # Mod list buttons
        button_layout = QHBoxLayout()
       
        self.add_to_order_btn = QPushButton("Add to Load Order")
        self.add_to_order_btn.clicked.connect(self.add_selected_to_order)
        button_layout.addWidget(self.add_to_order_btn)
       
        self.toggle_favorite_btn = QPushButton("Toggle Favorite")
        self.toggle_favorite_btn.clicked.connect(self.toggle_favorite)
        button_layout.addWidget(self.toggle_favorite_btn)
       
        mod_list_layout.addLayout(button_layout)
       
        splitter.addWidget(mod_list_widget)
       
        # Mod details
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
       
        details_layout.addWidget(QLabel("Mod Details:"))
       
        self.mod_details_text = QTextBrowser()
        self.mod_details_text.setReadOnly(True)
        # Open links in external browser
        try:
            # QTextBrowser emits anchorClicked with a QUrl
            self.mod_details_text.anchorClicked.connect(lambda url: webbrowser.open(url.toString()))
        except Exception:
            pass
        details_layout.addWidget(self.mod_details_text)
       
        splitter.addWidget(details_widget)
        splitter.setSizes([400, 300])
       
        layout.addWidget(splitter)
       
        self.tab_widget.addTab(tab, "Mod Browser")
   
    def create_load_order_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
       
        # Load order controls
        controls_layout = QHBoxLayout()
       
        self.optimize_btn = QPushButton("Optimize Load Order")
        self.optimize_btn.clicked.connect(self.optimize_load_order)
        controls_layout.addWidget(self.optimize_btn)
       
        self.clear_order_btn = QPushButton("Clear Load Order")
        self.clear_order_btn.clicked.connect(self.clear_load_order)
        controls_layout.addWidget(self.clear_order_btn)
       
        self.save_preset_btn = QPushButton("Save as Preset...")
        self.save_preset_btn.clicked.connect(self.save_load_order_preset)
        controls_layout.addWidget(self.save_preset_btn)
       
        self.load_preset_btn = QPushButton("Load Preset...")
        self.load_preset_btn.clicked.connect(self.load_preset_dialog)
        controls_layout.addWidget(self.load_preset_btn)
       
        controls_layout.addStretch()
       
        layout.addLayout(controls_layout)
       
        # Load order list
        self.load_order_widget = LoadOrderWidget()
        self.load_order_widget.itemMoved.connect(self.on_load_order_changed)
        layout.addWidget(self.load_order_widget)
       
        # Validation section
        validation_group = QGroupBox("Load Order Validation")
        validation_layout = QVBoxLayout()
       
        self.validation_text = QTextEdit()
        self.validation_text.setReadOnly(True)
        self.validation_text.setMaximumHeight(100)
        validation_layout.addWidget(self.validation_text)
       
        validation_group.setLayout(validation_layout)
        layout.addWidget(validation_group)
       
        self.tab_widget.addTab(tab, "Load Order")
   
    def create_favorites_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
       
        layout.addWidget(QLabel("Favorite Mods:"))
       
        self.favorites_list = ModListWidget()
        self.favorites_list.itemDoubleClicked.connect(self.on_favorite_double_clicked)
        layout.addWidget(self.favorites_list)
       
        # Favorites buttons
        fav_buttons_layout = QHBoxLayout()
       
        add_fav_to_order_btn = QPushButton("Add to Load Order")
        add_fav_to_order_btn.clicked.connect(lambda: self.add_favorites_to_order())
        fav_buttons_layout.addWidget(add_fav_to_order_btn)
       
        remove_favorite_btn = QPushButton("Remove from Favorites")
        remove_favorite_btn.clicked.connect(self.remove_selected_favorite)
        fav_buttons_layout.addWidget(remove_favorite_btn)
       
        fav_buttons_layout.addStretch()
       
        layout.addLayout(fav_buttons_layout)
       
        self.tab_widget.addTab(tab, "Favorites")
   
    def load_mod_data(self):
        """Load mods from database"""
        self.status_bar.showMessage("Loading mods...")
       
        mods = self.database.get_all_mods()
        self.mod_data_map = {mod['id']: mod for mod in mods}
       
        self.populate_mod_list(mods)
        self.populate_favorites()
       
        self.status_bar.showMessage(f"Loaded {len(mods)} mods")
   
    def populate_mod_list(self, mods):
        """Populate the mod list widget"""
        self.mod_list.clear()
       
        for mod in mods:
            self.mod_list.add_mod_item(mod, mod.get('is_favorite', False))
   
    def populate_favorites(self):
        """Populate favorites list"""
        favorites = self.database.get_favorite_mods()
        self.favorites_list.clear()
       
        for mod in favorites:
            self.favorites_list.add_mod_item(mod, True)
   
    def filter_mods(self):
        """Filter mods based on search and category"""
        search_text = self.search_edit.text().lower()
        category = self.category_combo.currentText()
        show_collections = getattr(self, 'show_collections_check', None) and self.show_collections_check.isChecked()
       
        mods = self.database.get_all_mods()
        filtered_mods = []
       
        for mod in mods:
            # Search filter
            matches_search = (search_text in mod['title'].lower() or
                            search_text in mod.get('description', '').lower() or
                            any(search_text in tag.lower() for tag in mod.get('tags', [])))
           
            # Category filter
            matches_category = (category == "All Categories" or
                              category.lower() in mod['title'].lower() or
                              any(category.lower() == tag.lower() for tag in mod.get('tags', [])))
           
            # Determine whether this mod is a collection (if we have the raw filetype)
            rt = mod.get('raw_filetype') or mod.get('file_type') or mod.get('filetype')
            is_collection = (rt is not None and str(rt) == '2')

            if not show_collections and is_collection:
                continue

            if matches_search and matches_category:
                filtered_mods.append(mod)
       
        self.populate_mod_list(filtered_mods)
   
    def on_mod_double_clicked(self, item):
        """Show mod details when double-clicked"""
        mod_id = item.data(Qt.ItemDataRole.UserRole)
        mod_data = self.mod_data_map.get(mod_id)
       
        if not mod_data:
            return

        # Ensure we have an API client to fetch details (no API key required for published file details)
        if not getattr(self, 'steam_api', None):
            api_key = self.database.get_setting('steam_api_key')
            self.steam_api = SteamAPI(api_key)

        # Try to fetch more detailed info (description, creator name, file size, etc.)
        try:
            if getattr(self, 'steam_api', None):
                details_list = self.steam_api.get_mod_details([mod_id])
                
                if details_list:
                    # merge details into local mod_data
                    detail = details_list[0]
                    for k, v in detail.items():
                        if v is not None:
                            mod_data[k] = v
                    # store back into map
                    self.mod_data_map[mod_id] = mod_data
        except Exception:
            pass

        # Basic fields (prefer enriched fields)
        title = mod_data.get('title', 'Unknown')
        creator_name = mod_data.get('creator_name') or mod_data.get('creator') or 'Unknown'
        subscriptions = mod_data.get('subscriptions', 0)
        favorites = mod_data.get('favorites') if mod_data.get('favorites') is not None else 'N/A'
        file_size = mod_data.get('file_size')
        time_created = mod_data.get('time_created')
        time_updated = mod_data.get('time_updated')

        def fmt_ts(ts):
            try:
                ts_i = int(ts)
                return datetime.fromtimestamp(ts_i).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                return 'N/A'

        def fmt_bytes(b):
            try:
                b_i = int(b)
            except Exception:
                return 'N/A'
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if b_i < 1024.0:
                    return f"{b_i:3.1f} {unit}"
                b_i /= 1024.0
            return f"{b_i:.1f} PB"

        workshop_url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}"

        details = f"<h2>{title}</h2>"
        details += f"<p><b>Mod ID:</b> {mod_id}</p>"
        details += f"<p><b>Workshop Page:</b> <a href=\"{workshop_url}\">Open on Steam Workshop</a></p>"
        details += f"<p><b>Creator:</b> {creator_name}</p>"
        details += f"<p><b>Subscriptions:</b> {subscriptions:,}</p>"
        details += f"<p><b>Favorites:</b> {favorites}</p>"
        details += f"<p><b>Time Created:</b> {fmt_ts(time_created) if time_created else 'N/A'}</p>"
        details += f"<p><b>Time Updated:</b> {fmt_ts(time_updated) if time_updated else 'N/A'}</p>"
        details += f"<p><b>File Size:</b> {fmt_bytes(file_size) if file_size else 'N/A'}</p>"

        if mod_data.get('tags'):
            details += f"<p><b>Tags:</b> {', '.join(mod_data['tags'])}</p>"

        # Preview image: try to download locally and embed
        img_html = ''
        preview_url = mod_data.get('preview_url') or mod_data.get('preview')
        if preview_url:
            try:
                import tempfile
                import os
                resp = requests.get(preview_url, timeout=10)
                resp.raise_for_status()
                content_type = (resp.headers.get('content-type') or '').lower()
                # guess extension
                if 'jpeg' in content_type or preview_url.lower().endswith(('.jpg', '.jpeg')):
                    ext = 'jpg'
                elif 'png' in content_type or preview_url.lower().endswith('.png'):
                    ext = 'png'
                else:
                    ext = 'img'

                tmp_path = os.path.join(tempfile.gettempdir(), f"mod_preview_{mod_id}.{ext}")
                with open(tmp_path, 'wb') as fh:
                    fh.write(resp.content)

                img_src = tmp_path.replace('\\', '/')
                img_html = f'<div style="margin:8px 0;"><img src="file:///{img_src}" style="max-width:100%;height:auto;"/></div>'
            except Exception:
                img_html = ''

        # Full description (allow basic HTML, remove scripts/styles)
        desc_raw = mod_data.get('description') or ''
        import re
        desc_sanitized = re.sub(r'(?is)<(script|style).*?>.*?</\1>', '', desc_raw)
        desc_sanitized = desc_sanitized.strip()
        if not desc_sanitized:
            desc_html = '<em>No description</em>'
        else:
            desc_html = desc_sanitized

        details += img_html + f"<h3>Description</h3>{desc_html}"

        self.mod_details_text.setHtml(details)
   
    def on_favorite_double_clicked(self, item):
        """Add favorite mod to load order when double-clicked"""
        mod_id = item.data(Qt.ItemDataRole.UserRole)
        self.add_mod_to_order(mod_id)
   
    def add_selected_to_order(self):
        """Add selected mods to load order"""
        selected_items = self.mod_list.selectedItems()
       
        for item in selected_items:
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            self.add_mod_to_order(mod_id)
   
    def add_favorites_to_order(self):
        """Add all favorites to load order"""
        favorites = self.database.get_favorite_mods()
       
        for mod in favorites:
            self.add_mod_to_order(mod['id'])
   
    def add_mod_to_order(self, mod_id):
        """Add a specific mod to the load order"""
        if mod_id in self.current_load_order:
            return  # Already in load order
       
        mod_data = self.mod_data_map.get(mod_id)
        if not mod_data:
            return
       
        self.load_order_widget.add_mod_item(mod_data)
        self.current_load_order.append(mod_id)
       
        # Validate load order
        self.validate_load_order()
   
    def toggle_favorite(self):
        """Toggle favorite status for selected mods"""
        selected_items = self.mod_list.selectedItems()
       
        for item in selected_items:
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            mod_data = self.mod_data_map.get(mod_id)
           
            if mod_data:
                if mod_data.get('is_favorite'):
                    self.database.remove_favorite(mod_id)
                    mod_data['is_favorite'] = False
                    # Update item color
                    item.setForeground(QColor(255, 255, 255))
                else:
                    self.database.add_favorite(mod_id)
                    mod_data['is_favorite'] = True
                    # Update item color
                    item.setForeground(QColor(255, 140, 0))
       
        # Refresh favorites list
        self.populate_favorites()
   
    def remove_selected_favorite(self):
        """Remove selected mods from favorites"""
        selected_items = self.favorites_list.selectedItems()
       
        for item in selected_items:
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            self.database.remove_favorite(mod_id)
           
            # Update mod_data_map
            if mod_id in self.mod_data_map:
                self.mod_data_map[mod_id]['is_favorite'] = False
       
        # Refresh both lists
        self.populate_favorites()
        self.filter_mods()
   
    def optimize_load_order(self):
        """Optimize the current load order"""
        if not self.current_load_order:
            QMessageBox.warning(self, "No Mods", "Load order is empty.")
            return
       
        # Generate optimized load order
        optimized_order = self.load_order_engine.generate_load_order(
            self.current_load_order,
            self.mod_data_map
        )
       
        # Check for conflicts and dependencies
        conflicts = self.load_order_engine.check_conflicts(optimized_order)
        missing_deps = self.load_order_engine.check_dependencies(optimized_order)
       
        # Update load order display
        self.load_order_widget.clear()
        self.current_load_order = []
       
        for mod_id in optimized_order:
            mod_data = self.mod_data_map.get(mod_id)
            if mod_data:
                self.load_order_widget.add_mod_item(mod_data)
                self.current_load_order.append(mod_id)
       
        # Show validation results
        self.show_validation_results(conflicts, missing_deps)
       
        if not conflicts and not missing_deps:
            self.status_bar.showMessage("Load order optimized successfully!")
   
    def clear_load_order(self):
        """Clear the current load order"""
        reply = QMessageBox.question(
            self, 'Clear Load Order',
            'Are you sure you want to clear the load order?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
       
        if reply == QMessageBox.StandardButton.Yes:
            self.load_order_widget.clear()
            self.current_load_order = []
            self.validation_text.clear()
   
    def on_load_order_changed(self):
        """Update current load order when items are moved"""
        self.current_load_order = self.load_order_widget.get_load_order()
        self.validate_load_order()
   
    def validate_load_order(self):
        """Validate the current load order"""
        if not self.current_load_order:
            self.validation_text.clear()
            return
       
        conflicts = self.load_order_engine.check_conflicts(self.current_load_order)
        missing_deps = self.load_order_engine.check_dependencies(self.current_load_order)
       
        self.show_validation_results(conflicts, missing_deps)
   
    def show_validation_results(self, conflicts, missing_deps):
        """Display validation results in the validation text box"""
        validation_text = ""
       
        if conflicts:
            validation_text += "<b>⚠ CONFLICTS DETECTED:</b><br>"
            for mod_id, target_id, notes in conflicts:
                mod_name = self.mod_data_map.get(mod_id, {}).get('title', mod_id)
                target_name = self.mod_data_map.get(target_id, {}).get('title', target_id)
                validation_text += f"• {mod_name} conflicts with {target_name}"
                if notes:
                    validation_text += f" ({notes})"
                validation_text += "<br>"
            validation_text += "<br>"
       
        if missing_deps:
            validation_text += "<b>⚠ MISSING DEPENDENCIES:</b><br>"
            for mod_id, dep_id, notes in missing_deps:
                mod_name = self.mod_data_map.get(mod_id, {}).get('title', mod_id)
                dep_name = self.mod_data_map.get(dep_id, {}).get('title', dep_id)
                validation_text += f"• {mod_name} requires {dep_name}"
                if notes:
                    validation_text += f" ({notes})"
                validation_text += "<br>"
       
        if not conflicts and not missing_deps:
            validation_text += "<b style='color: green'>✓ Load order is valid</b>"
       
        self.validation_text.setHtml(validation_text)
   
    def save_load_order_preset(self):
        """Save current load order as a preset"""
        if not self.current_load_order:
            QMessageBox.warning(self, "No Mods", "Load order is empty.")
            return
       
        name, ok = QInputDialog.getText(
            self, "Save Preset",
            "Enter a name for this load order preset:"
        )
       
        if ok and name:
            self.database.save_load_order_preset(name, self.current_load_order)
            self.status_bar.showMessage(f"Preset '{name}' saved.")
   
    def load_preset_dialog(self):
        """Dialog to load a saved preset"""
        presets = self.database.get_load_order_presets()
       
        if not presets:
            QMessageBox.information(self, "No Presets", "No saved presets found.")
            return
       
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Preset")
        dialog.setMinimumWidth(400)
       
        layout = QVBoxLayout(dialog)
       
        # Preset list
        preset_list = QListWidget()
        for preset in presets:
            item = QListWidgetItem(f"{preset['name']} ({len(preset['mod_ids'])} mods)")
            item.setData(Qt.ItemDataRole.UserRole, preset['id'])
            preset_list.addItem(item)
       
        layout.addWidget(preset_list)
       
        # Buttons
        button_layout = QHBoxLayout()
       
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(lambda: self.load_selected_preset(preset_list, dialog))
        button_layout.addWidget(load_btn)
       
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(lambda: self.delete_selected_preset(preset_list))
        button_layout.addWidget(delete_btn)
       
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_btn)
       
        layout.addLayout(button_layout)
       
        dialog.exec()
   
    def load_selected_preset(self, preset_list, dialog):
        """Load the selected preset"""
        selected_items = preset_list.selectedItems()
        if not selected_items:
            return
       
        preset_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
        presets = self.database.get_load_order_presets()
       
        for preset in presets:
            if preset['id'] == preset_id:
                # Clear current load order
                self.load_order_widget.clear()
                self.current_load_order = []
               
                # Load preset
                for mod_id in preset['mod_ids']:
                    mod_data = self.mod_data_map.get(mod_id)
                    if mod_data:
                        self.load_order_widget.add_mod_item(mod_data)
                        self.current_load_order.append(mod_id)
               
                # Validate
                self.validate_load_order()
               
                # Update last used timestamp
                self.database.save_load_order_preset(preset['name'], preset['mod_ids'])
               
                self.status_bar.showMessage(f"Loaded preset '{preset['name']}'")
                break
       
        dialog.accept()
   
    def delete_selected_preset(self, preset_list):
        """Delete the selected preset"""
        selected_items = preset_list.selectedItems()
        if not selected_items:
            return
       
        preset_id = selected_items[0].data(Qt.ItemDataRole.UserRole)
       
        reply = QMessageBox.question(
            self, 'Delete Preset',
            'Are you sure you want to delete this preset?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
       
        if reply == QMessageBox.StandardButton.Yes:
            self.database.delete_load_order_preset(preset_id)
            preset_list.takeItem(preset_list.row(selected_items[0]))
            self.status_bar.showMessage("Preset deleted.")
   
    def export_load_order(self):
        """Export current load order to modlist.txt"""
        if not self.current_load_order:
            QMessageBox.warning(self, "No Mods", "Load order is empty.")
            return
       
        # Get export path
        default_path = self.database.get_setting('conan_install_path', '')
        if default_path:
            default_path = os.path.join(default_path, "ConanSandbox", "Mods", "modlist.txt")
       
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Load Order",
            default_path,
            "Text Files (*.txt);;All Files (*.*)"
        )
       
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    for mod_id in self.current_load_order:
                        f.write(f"{mod_id}\n")
               
                self.status_bar.showMessage(f"Load order exported to {file_path}")
                QMessageBox.information(self, "Export Complete",
                                      f"Load order exported successfully!\n\n"
                                      f"File: {file_path}\n"
                                      f"Mods: {len(self.current_load_order)}")
               
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export load order:\n{str(e)}")
   
    def update_mods(self):
        """Update mod list from Steam Workshop"""
        api_key = self.database.get_setting('steam_api_key')
       
        if not api_key:
            QMessageBox.warning(self, "API Key Required",
                              "Please set your Steam Web API key in Settings first.")
            self.open_settings()
            return
       
        # Create progress dialog
        self.progress_dialog = QDialog(self)
        self.progress_dialog.setWindowTitle("Updating Mods")
        self.progress_dialog.setModal(True)
        self.progress_dialog.setFixedSize(400, 150)
       
        layout = QVBoxLayout(self.progress_dialog)
       
        self.progress_label = QLabel("Preparing to update mods...")
        layout.addWidget(self.progress_label)
       
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
       
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.cancel_update)
        layout.addWidget(cancel_btn)
       
        self.progress_dialog.show()
       
        # Create and start update thread
        self.steam_api = SteamAPI(api_key)
        self.update_thread = UpdateThread(self.steam_api, self.database)
        self.update_thread.update_progress.connect(self.on_update_progress)
        self.update_thread.update_finished.connect(self.on_update_finished)
        self.update_thread.update_error.connect(self.on_update_error)
        self.update_thread.start()
   
    def on_update_progress(self, progress, message):
        """Handle progress updates"""
        self.progress_bar.setValue(progress)
        self.progress_label.setText(message)
   
    def on_update_finished(self, mods):
        """Handle update completion"""
        self.progress_dialog.close()
       
        # Reload mod data
        self.load_mod_data()
       
        QMessageBox.information(self, "Update Complete",
                              f"Successfully updated {len(mods)} mods from Steam Workshop.")
   
    def on_update_error(self, error_message):
        """Handle update errors"""
        self.progress_dialog.close()
        QMessageBox.critical(self, "Update Error", f"Failed to update mods:\n{error_message}")
   
    def cancel_update(self):
        """Cancel the update process"""
        if hasattr(self, 'update_thread') and self.update_thread.isRunning():
            self.update_thread.stop()
            self.update_thread.wait()
       
        self.progress_dialog.close()
        self.status_bar.showMessage("Update cancelled.")
   
    def check_for_updates(self):
        """Check if mod list needs updating"""
        last_check = self.database.get_setting('last_update_check')
       
        if not last_check:
            # First run, check for updates
            self.database.save_setting('last_update_check', datetime.now().isoformat())
            return
       
        last_check_dt = datetime.fromisoformat(last_check)
        update_interval = int(self.database.get_setting('auto_update_interval', '24'))
       
        if datetime.now() - last_check_dt > timedelta(hours=update_interval):
            # Ask user if they want to update
            reply = QMessageBox.question(
                self, 'Update Available',
                f'It has been more than {update_interval} hours since the last update.\n'
                'Would you like to update the mod list now?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
           
            if reply == QMessageBox.StandardButton.Yes:
                self.update_mods()
   
    def open_settings(self):
        """Open settings dialog"""
        dialog = SettingsDialog(self)
        dialog.exec()
       
        # Update API key if changed
        api_key = self.database.get_setting('steam_api_key')
        if api_key:
            self.steam_api = SteamAPI(api_key)
   
    def show_about(self):
        """Show about dialog"""
        about_text = """
        <h1>Conan Exiles Mod Manager</h1>
        <p><b>Version:</b> 1.0.0</p>
        <p><b>Features:</b></p>
        <ul>
            <li>Browse all Conan Exiles Steam Workshop mods</li>
            <li>Save favorite mods for quick access</li>
            <li>Create and optimize load orders</li>
            <li>Detect mod conflicts and missing dependencies</li>
            <li>Save and load load order presets</li>
            <li>Export to modlist.txt for game/server use</li>
            <li>Automatic updates from Steam Workshop</li>
        </ul>
        <p><b>Note:</b> A free Steam Web API key is required for mod updates.</p>
        """
       
        QMessageBox.about(self, "About Conan Exiles Mod Manager", about_text)

 # ==================== APPLICATION ENTRY POINT ====================

def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName("Conan Exiles Mod Manager")
   
    # Check for required API key on first run
    db = Database()
    api_key = db.get_setting('steam_api_key')
   
    if not api_key:
        reply = QMessageBox.information(
            None,
            "Steam API Key Required",
            "This application requires a free Steam Web API key to fetch mod data.\n\n"
            "You can get one from: https://steamcommunity.com/dev/apikey\n\n"
            "Would you like to open the Steam API key page in your browser?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
       
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open("https://steamcommunity.com/dev/apikey")
   
    window = MainWindow()
    window.show()
   
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 

