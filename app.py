from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, jsonify, g, send_file
from docx import Document
from openai import AzureOpenAI
from dotenv import load_dotenv
import os
import time
from datetime import datetime, timedelta
import requests
import markdown
from bs4 import BeautifulSoup
from flask_session import Session
import json
import pyodbc
from io import BytesIO
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
import re
from docx.oxml.shared import OxmlElement
from docx.oxml.ns import qn
import hashlib
import secrets
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import base64
import io
from PIL import Image
import uuid
from urllib.parse import unquote
import asyncio
import httpx
import random
import aiohttp



load_dotenv()

app = Flask(__name__, static_folder='static')
app.secret_key = os.getenv('FLASK_SECRET_KEY')
app.config['UPLOAD_FOLDER'] = 'static/generated'

# Database configuration
app.config['AZURE_SQL_SERVER'] = os.getenv('AZURE_SQL_SERVER')
app.config['AZURE_SQL_DATABASE'] = os.getenv('AZURE_SQL_DATABASE')
app.config['AZURE_SQL_USERNAME'] = os.getenv('AZURE_SQL_USERNAME')
app.config['AZURE_SQL_PASSWORD'] = os.getenv('AZURE_SQL_PASSWORD')

# Session configuration
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
FUNCTION_APP_URL = os.getenv("AZURE_FUNCTION_APP_URL")
FUNCTION_KEY = os.getenv("FUNCTION_KEY")
Session(app)

# Simulate OpenAI calls for testing
SIMULATE_OPENAI = os.getenv("SIMULATE_OPENAI", "false").lower() == "true"

async def simulate_openai_call():
    """Simulate OpenAI call with random delay"""
    delay = random.uniform(20, 40)  # Random delay between 20-40 seconds
    await asyncio.sleep(delay)
    return {"content": "Simulated response after delay"}


async def make_async_request(url, payload):
    """Make async HTTP request with error handling"""
    if SIMULATE_OPENAI:
        return await simulate_openai_call()

    async with httpx.AsyncClient(timeout=60.0) as client:  # Create new client per request
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"Request error: {e}")
            raise
        except httpx.HTTPStatusError as e:
            print(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise


def get_db():
    if 'db' not in g:
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={app.config['AZURE_SQL_SERVER']};"
            f"DATABASE={app.config['AZURE_SQL_DATABASE']};"
            f"UID={app.config['AZURE_SQL_USERNAME']};"
            f"PWD={app.config['AZURE_SQL_PASSWORD']};"
            "Encrypt=yes;TrustServerCertificate=no;"
        )
        g.db = pyodbc.connect(conn_str)
    return g.db

def close_db():
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        
        # Create users table if it doesn't exist
        cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'users')
        CREATE TABLE users (
            id INT IDENTITY(1,1) PRIMARY KEY,
            username NVARCHAR(255) UNIQUE NOT NULL,
            email NVARCHAR(255) UNIQUE NOT NULL,
            password NVARCHAR(500) NOT NULL,
            firm NVARCHAR(255),
            location NVARCHAR(255),
            lawyer_name NVARCHAR(255),
            state NVARCHAR(50),
            address NVARCHAR(255),
            planning_session NVARCHAR(255),
            other_planning_session NVARCHAR(255),
            discovery_call_link NVARCHAR(255)
        )
        ''')
        
        # Add new columns if they don't exist
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'address')
            ALTER TABLE users ADD address NVARCHAR(255)
            ''')
        except pyodbc.Error:
            pass
            
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'planning_session')
            ALTER TABLE users ADD planning_session NVARCHAR(255)
            ''')
        except pyodbc.Error:
            pass
            
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'other_planning_session')
            ALTER TABLE users ADD other_planning_session NVARCHAR(255)
            ''')
        except pyodbc.Error:
            pass
            
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'discovery_call_link')
            ALTER TABLE users ADD discovery_call_link NVARCHAR(255)
            ''')
        except pyodbc.Error:
            pass
            
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'selected_tone')
            ALTER TABLE users ADD selected_tone NVARCHAR(255)
            ''')
        except pyodbc.Error:
            pass
            
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'tone_description')
            ALTER TABLE users ADD tone_description NVARCHAR(MAX)
            ''')
        except pyodbc.Error:
            pass
            
        try:
            cursor.execute('''
            IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('users') AND name = 'keywords')
            ALTER TABLE users ADD keywords NVARCHAR(MAX)
            ''')
        except pyodbc.Error:
            pass
        
        # Update password column size to accommodate hashed passwords
        try:
            cursor.execute('''
            ALTER TABLE users ALTER COLUMN password NVARCHAR(500)
            ''')
        except pyodbc.Error:
            pass
        
        # Create tones table if it doesn't exist
        cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'tones')
        CREATE TABLE tones (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT NOT NULL,
            name NVARCHAR(255) NOT NULL,
            description NVARCHAR(MAX) NOT NULL,
            CONSTRAINT UQ_user_tone UNIQUE(user_id, name),
            CONSTRAINT FK_user_tone FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')
        
        # Check if default users exist
        cursor.execute("SELECT * FROM users WHERE username IN ('admin', 'memberhub')")
        existing_users = cursor.fetchall()
        existing_usernames = [user.username for user in existing_users]
        
        if 'admin' not in existing_usernames:
            cursor.execute('''
            INSERT INTO users (username, email, password, firm, location, lawyer_name, state, address, 
                             planning_session, other_planning_session, discovery_call_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'admin', 
                'admin@lawfirm.com', 
                'password123', 
                'Legal Partners', 
                'New York', 
                'John', 
                'NY',
                '',
                '',
                '',
                ''
            ))
        
        if 'memberhub' not in existing_usernames:
            cursor.execute('''
            INSERT INTO users (username, email, password, firm, location, lawyer_name, state, address, 
                             planning_session, other_planning_session, discovery_call_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'memberhub', 
                'memberhub@newlawbusinessmodel.com', 
                'memberhub123', 
                'New Law Business Model', 
                'Global', 
                'Member Hub', 
                'CA',
                '',
                '',
                '',
                ''
            ))
        
        # Create password_resets table if it doesn't exist
        cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='password_resets' AND xtype='U')
        CREATE TABLE password_resets (
            id INTEGER IDENTITY(1,1) PRIMARY KEY,
            email NVARCHAR(255) NOT NULL,
            token NVARCHAR(255) NOT NULL UNIQUE,
            expires DATETIME NOT NULL,
            used INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT GETDATE()
        )
        ''')
        
        # Create feedback table if it doesn't exist
        cursor.execute('''
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'feedback')
        CREATE TABLE feedback (
            id INT IDENTITY(1,1) PRIMARY KEY,
            user_id INT,
            feedback_type NVARCHAR(50) NOT NULL,
            priority NVARCHAR(20) NOT NULL,
            subject NVARCHAR(255) NOT NULL,
            message NVARCHAR(MAX) NOT NULL,
            contact_email NVARCHAR(255),
            status NVARCHAR(20) DEFAULT 'pending',
            created_at DATETIME DEFAULT GETDATE(),
            updated_at DATETIME DEFAULT GETDATE(),
            CONSTRAINT FK_feedback_user FOREIGN KEY(user_id) REFERENCES users(id)
        )
        ''')
        
        db.commit()

# Initialize database
with app.app_context():
    init_db()

# Add context processor to inject current year into all templates
@app.context_processor
def inject_year():
    return {'now': datetime.now()}

class UserSession:
    @staticmethod
    def register(email, password, firm, location, lawyer_name, state, address="", planning_session="", other_planning_session="", discovery_call_link=""):
        db = get_db()
        username = email.split('@')[0].lower()
        try:
            cursor = db.cursor()
            cursor.execute('''
            INSERT INTO users (username, email, password, firm, location, lawyer_name, state, address, 
                             planning_session, other_planning_session, discovery_call_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (username, email, password, firm, location, lawyer_name, state, address, 
                 planning_session, other_planning_session, discovery_call_link))
            db.commit()
            return True
        except pyodbc.IntegrityError:
            return False

    @staticmethod
    def login(email, password):
        db = get_db()
        username = email.split('@')[0].lower()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if user and user.password == password:
            # Get user's custom tones
            cursor.execute('SELECT name, description FROM tones WHERE user_id = ?', (user.id,))
            tones = cursor.fetchall()
            
            session['user'] = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'firm': user.firm,
                'location': user.location,
                'lawyer_name': user.lawyer_name,
                'state': user.state,
                'address': user.address,
                'planning_session': user.planning_session,
                'other_planning_session': user.other_planning_session,
                'discovery_call_link': user.discovery_call_link,
                'custom_tones': [{'name': tone.name, 'description': tone.description} for tone in tones]
            }
            return True
        return False

    @staticmethod
    def update_profile(username, firm, location, lawyer_name, state, address="", planning_session="", other_planning_session="", discovery_call_link="", selected_tone="", tone_description="", keywords=""):
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute('''
            UPDATE users 
            SET firm = ?, location = ?, lawyer_name = ?, state = ?, 
                address = ?, planning_session = ?, other_planning_session = ?, discovery_call_link = ?,
                selected_tone = ?, tone_description = ?, keywords = ?
            WHERE username = ?
            ''', (firm, location, lawyer_name, state, address, planning_session, 
                 other_planning_session, discovery_call_link, selected_tone, tone_description, keywords, username))
            db.commit()
            
            # Update session if this is the current user
            if 'user' in session and session['user']['username'] == username:
                session['user'].update({
                    'firm': firm,
                    'location': location,
                    'lawyer_name': lawyer_name,
                    'state': state,
                    'address': address,
                    'planning_session': planning_session,
                    'other_planning_session': other_planning_session,
                    'discovery_call_link': discovery_call_link,
                    'selected_tone': selected_tone,
                    'tone_description': tone_description,
                    'keywords': keywords
                })
                session.modified = True
            return True
        except pyodbc.Error:
            return False

    @staticmethod
    def get_current_user():
        return session.get('user')

    @staticmethod
    def add_custom_tone(user_id, tone_name, tone_description):
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute('''
            INSERT INTO tones (user_id, name, description)
            VALUES (?, ?, ?)
            ''', (user_id, tone_name, tone_description))
            db.commit()
            
            # Update session if this is the current user
            if 'user' in session and session['user']['id'] == user_id:
                session['user']['custom_tones'].append({
                    'name': tone_name,
                    'description': tone_description
                })
                session.modified = True
            return True
        except pyodbc.IntegrityError:
            return False
    
    @staticmethod
    def get_custom_tones(user_id):
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT name, description FROM tones WHERE user_id = ?', (user_id,))
        tones = cursor.fetchall()
        return [{'name': tone.name, 'description': tone.description} for tone in tones]

    @staticmethod
    def submit_feedback(user_id, feedback_type, priority, subject, message, contact_email=None):
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute('''
            INSERT INTO feedback (user_id, feedback_type, priority, subject, message, contact_email)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, feedback_type, priority, subject, message, contact_email))
            db.commit()
            return True
        except Exception as e:
            print(f"Error submitting feedback: {str(e)}")
            return False

class Config:
    ARTICLES_DIR = "articles"
    GENERATED_DIR = "generated"
    os.makedirs(ARTICLES_DIR, exist_ok=True)
    os.makedirs(GENERATED_DIR, exist_ok=True)

    # Default section markers (can be updated based on client requirements)
    SECTION_MARKERS = {
        'hook': {
            'start': 0,  # First paragraph
            'end': 1     # End of first paragraph
        },
        'summary': {
            'start': 1,  # Second paragraph (2-3 lines ending with "read more...")
            'end': 2     # End of second paragraph
        },
        'disclaimer': {
            'start': -1,  # Last paragraph (disclaimer)
            'end': None   # End of content
        }
    }

class AzureServices:
    def __init__(self):
        self.text_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2024-02-15-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )
        
        self.conversations = {}

    def _extract_sections(self, content):
        """Extract and preserve specific sections from the content."""
        try:
            paragraphs = content.split('\n\n')
            preserved_sections = {}
            
            print(f"\n=== EXTRACTING SECTIONS ===")
            print(f"Total paragraphs found: {len(paragraphs)}")
            
            # Extract Hook (first paragraph)
            hook_start = Config.SECTION_MARKERS['hook']['start']
            hook_end = Config.SECTION_MARKERS['hook']['end']
            if hook_start < len(paragraphs):
                preserved_sections['hook'] = paragraphs[hook_start:hook_end][0] if hook_end - hook_start == 1 else '\n\n'.join(paragraphs[hook_start:hook_end])
                print(f"✓ Extracted Hook (paragraph 1): {preserved_sections['hook'][:100]}...")
            else:
                print("✗ Warning: Hook section not found in content")
                preserved_sections['hook'] = ""
            
            # Extract Summary (second paragraph - should be 2-3 lines ending with "read more...")
            summary_start = Config.SECTION_MARKERS['summary']['start']
            summary_end = Config.SECTION_MARKERS['summary']['end']
            if summary_start < len(paragraphs):
                preserved_sections['summary'] = paragraphs[summary_start:summary_end][0] if summary_end - summary_start == 1 else '\n\n'.join(paragraphs[summary_start:summary_end])
                print(f"✓ Extracted Summary (paragraph 2): {preserved_sections['summary'][:100]}...")
            else:
                print("✗ Warning: Summary section not found in content")
                preserved_sections['summary'] = ""
            

            
            # Extract Disclaimer (last paragraph)
            disclaimer_start = Config.SECTION_MARKERS['disclaimer']['start']
            if len(paragraphs) > 0:
                preserved_sections['disclaimer'] = paragraphs[disclaimer_start]
                print(f"✓ Extracted Disclaimer (paragraph {len(paragraphs)}): {preserved_sections['disclaimer'][:100]}...")
            else:
                print("✗ Warning: Disclaimer section not found in content")
                preserved_sections['disclaimer'] = ""
            
            print("=== SECTION EXTRACTION COMPLETE ===\n")
            
            return preserved_sections
        except Exception as e:
            print(f"Error extracting sections: {str(e)}")
            return {'hook': "", 'summary': "", 'disclaimer': ""}

    def _reconstruct_content(self, new_content, preserved_sections):
        """Preserve specific sections exactly as they are in the original content."""
        try:
            paragraphs = new_content.split('\n\n')
            
            print(f"\n=== RECONSTRUCTING CONTENT ===")
            print(f"Total paragraphs in new content: {len(paragraphs)}")
            
            # Remove any existing disclaimer or service description from the middle of the content
            # to prevent duplication, but preserve CTA content
            cleaned_paragraphs = []
            for i, para in enumerate(paragraphs):
                # Skip paragraphs that are exact matches of disclaimers or service descriptions
                # But preserve paragraphs that contain CTA phrases
                is_duplicate_section = False
                if preserved_sections['disclaimer'] and preserved_sections['disclaimer'].strip() == para.strip():
                    is_duplicate_section = True
                    print(f"⚠️  Removed duplicate disclaimer from position {i+1}")

                
                if not is_duplicate_section:
                    cleaned_paragraphs.append(para)
            
            paragraphs = cleaned_paragraphs
            print(f"Paragraphs after cleaning: {len(paragraphs)}")
            
            # Place preserved sections in their correct positions
            # Hook (first paragraph)
            if preserved_sections['hook'] and len(paragraphs) > 0:
                paragraphs[0] = preserved_sections['hook']
                print("✓ Preserved Hook section at position 1")
            
            # Summary (second paragraph - 2-3 lines ending with "read more...")
            if preserved_sections['summary'] and len(paragraphs) > 1:
                paragraphs[1] = preserved_sections['summary']
                print("✓ Preserved Summary section at position 2")
            elif preserved_sections['summary'] and len(paragraphs) <= 1:
                # If there aren't enough paragraphs, add the summary as second paragraph
                if len(paragraphs) == 0:
                    paragraphs.append("")  # Add empty first paragraph if needed
                paragraphs.append(preserved_sections['summary'])
                print("✓ Added Summary section at position 2")
            

            
            # Disclaimer (last paragraph)
            if preserved_sections['disclaimer']:
                # Always add disclaimer at the very end
                paragraphs.append(preserved_sections['disclaimer'])
                print("✓ Added Disclaimer section at the very end")
            
            final_content = '\n\n'.join(paragraphs)
            
            # Verify sections are preserved exactly
            if preserved_sections['hook'] and preserved_sections['hook'] not in final_content:
                print("✗ Warning: Hook section not preserved exactly")
            if preserved_sections['summary'] and preserved_sections['summary'] not in final_content:
                print("✗ Warning: Summary section not preserved exactly")

            if preserved_sections['disclaimer'] and preserved_sections['disclaimer'] not in final_content:
                print("✗ Warning: Disclaimer section not preserved exactly")
            
            print("=== RECONSTRUCTION COMPLETE ===\n")
            
            return final_content
        except Exception as e:
            print(f"Error preserving sections: {str(e)}")
            return new_content

    def _validate_with_gpt(self, original_text, new_content, components):
        """Validate article components using GPT for better semantic understanding."""
        validation_prompt = f"""
            You are an expert content validator. Analyze these two articles and provide a detailed validation.
            You MUST respond with a valid JSON object following this EXACT structure, with no additional text:
            
            {{
                "components": {{
                    "keywords": {{
                        "found": true/false,
                        "occurrences": number,
                        "variations": ["variation1", "variation2"],
                        "in_first_150": true/false
                    }},
                    "firm_info": {{
                        "found": true/false,
                        "name": true/false,
                        "location": true/false
                    }},
                    "lawyer_info": {{
                        "found": true/false,
                        "name": true/false,
                        "location": true/false
                    }},
                    "planning_session": {{
                        "found": true/false,
                        "name": true/false,
                        "references": number
                    }},
                    "discovery_call": {{
                        "found": true/false,
                        "link": true/false,
                        "references": number
                    }}
                }},
                "preserved_sections": {{
                    "hook": true/false,
                    "summary": true/false,
                    "disclaimer": true/false
                }},
                "change_analysis": {{
                    "percentage": number,
                    "significant_changes": true/false,
                    "maintained_essence": true/false
                }},
                "warnings": ["warning1", "warning2"],
                "missing_components": ["component1", "component2"]
            }}

            Analyze the following content:

            Required components to check:
            - Keywords: {components['keywords']}
            - Firm: {components['firm_name']} in {components['location']}
            - Lawyer: {components['lawyer_name']} in {components['city']}, {components['state']}
            - Planning Session: {components['planning_session_name']}
            - Discovery Call: {components['discovery_call_link']}

            Original Article:
            {original_text}

            New Article:
            {new_content}

            Remember to respond with ONLY the JSON object, no additional text or explanation.
        """

        try:
            response = self.text_client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a JSON-only response validator. Always respond with valid JSON matching the exact structure provided."},
                    {"role": "user", "content": validation_prompt}
                ],
                temperature=0.1,  # Lower temperature for more consistent JSON output
                response_format={ "type": "json_object" }  # Force JSON response
            )

            # Get the response content and ensure it's valid JSON
            response_content = response.choices[0].message.content.strip()
            
            # Try to parse the JSON response
            try:
                validation_results = json.loads(response_content)
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {str(e)}")
                print(f"Raw response: {response_content}")
                raise

            # Validate the structure of the response
            required_keys = ['components', 'preserved_sections', 'change_analysis', 'warnings', 'missing_components']
            if not all(key in validation_results for key in required_keys):
                print("Invalid response structure. Missing required keys.")
                raise ValueError("Invalid response structure")

            # Print validation results in a readable format
            print("\n=== GPT Article Validation Results ===")
            
            print("\nComponent Status:")
            for component, details in validation_results['components'].items():
                status = '✓' if details.get('found', False) else '✗'
                print(f"- {component}: {status}")
                if component == 'keywords' and details.get('variations'):
                    print(f"  • Variations found: {', '.join(details['variations'])}")
                if 'occurrences' in details:
                    print(f"  • Occurrences: {details['occurrences']}")

            print("\nPreserved Sections:")
            for section, preserved in validation_results['preserved_sections'].items():
                print(f"- {section}: {'✓' if preserved else '✗'}")

            print(f"\nChange Analysis:")
            print(f"- Change Percentage: {validation_results['change_analysis']['percentage']:.1f}%")
            print(f"- Significant Changes: {'✓' if validation_results['change_analysis']['significant_changes'] else '✗'}")
            print(f"- Maintained Essence: {'✓' if validation_results['change_analysis']['maintained_essence'] else '✗'}")

            if validation_results['warnings']:
                print("\nWarnings:")
                for warning in validation_results['warnings']:
                    print(f"- {warning}")

            if validation_results['missing_components']:
                print("\nMissing Components:")
                for component in validation_results['missing_components']:
                    print(f"- {component}")

            print("===============================\n")

            return validation_results

        except Exception as e:
            print(f"Error in GPT validation: {str(e)}")
            print("Unable to validate article components. Please check the generated content manually.")
            return None

    def rewrite_content(self, original_text, tone, tone_description, keywords, firm_name, location, lawyer_name, city, state, discovery_call_link, planning_session_name="15-minute discovery call"):
        try:
            # Extract sections to preserve
            print("\nExtracting sections to preserve...")
            preserved_sections = self._extract_sections(original_text)
            
            # CRITICAL: DO NOT MODIFY THESE SECTIONS {preserved_sections}:
            # 1. The first paragraph (Hook) - which is this
            # 2. The fourth paragraph (Plug) - Keep it exactly as is
            # 3. The last paragraph (Disclaimer) - Keep it exactly as is
            
            # CRITICAL: DO NOT REPEAT THESE SECTIONS:
            # 1. The hook paragraph should appear ONLY ONCE at the beginning
            # 2. The plug paragraph should appear ONLY ONCE in its original position
            # 3. The disclaimer paragraph should appear ONLY ONCE at the end
            # 4. DO NOT include these preserved sections anywhere else in the article
            # 5. DO NOT create new paragraphs that repeat the same content as the hook, plug, or disclaimer

            # Add explicit instructions about preserving sections
            # CRITICAL: DO NOT REPEAT THESE SECTIONS:
            # 1. The first paragraph should appear ONLY ONCE at the beginning
            # 2. The second paragraph should appear ONLY ONCE in its original position
            # 3. The disclaimer paragraph should appear ONLY ONCE at the end
            # 4. DO NOT include these preserved sections anywhere else in the article
            # 5. DO NOT create new paragraphs that repeat the same content as the hook, plug, or disclaimer


            system_prompt = f"""
                You are a legal blog post rewriter. Generate ONLY the main article content (heading + body + CTA) with at least 40% changes from the original.
                
                TEMPLATE STRUCTURE (DO NOT INCLUDE THESE SECTIONS - THEY WILL BE ADDED AUTOMATICALLY):
                - Hook: {preserved_sections['hook']}
                - Summary: {preserved_sections['summary']}
                - Date: Will be added automatically
                - Disclaimer: {preserved_sections['disclaimer']}
                
                YOUR TASK: Generate ONLY the main content that goes in the template:
                1. Main heading (starts with "# ")
                2. Article body with subheadings (## )
                3. Call-to-action (CTA)
                
                The content will be inserted into a template that already includes:
                - Summary section
                - Date section  
                - Disclaimer section
                
                CRITICAL REQUIREMENTS:
                1. Start your content with the main heading: "# [Title]"
                2. Use proper markdown formatting throughout
                3. Include 3-4 subheadings with "## "
                4. End with a CTA paragraph
                5. DO NOT include hook, summary, date, or disclaimer
                6. DO NOT include any preview text or introductory paragraphs
                7. DO NOT include any dates
                8. Ensure at least 40% changes from original
                
                FORMATTING REQUIREMENTS:
                - Main heading: "# [Title]"
                - Subheadings: "## [Subheading]"
                - Bold text: **text**
                - Italic text: *text*
                - Bullet points: - or *
                - Proper line breaks between paragraphs
                
                SEO REQUIREMENTS:
                - Include keywords: {keywords}
                - Mention firm: {firm_name} in {location}
                - Mention lawyer: {lawyer_name} in {city}, {state}
                - Include planning session: {planning_session_name}
                - Include discovery call link: {discovery_call_link}
                
                TONE: {tone} - {tone_description}
                
                CTA REQUIREMENTS:
                - Use "15-minute discovery call" (lowercase) as clickable text
                - Format as markdown link: [15-minute discovery call]({discovery_call_link})
                - Include this link in the CTA paragraph
                - End content immediately after CTA
                
                LINK TEXT REQUIREMENTS:
                - Use descriptive link text that explains what the link does
                - DO NOT use generic phrases like "click here", "read more", "learn more"
                - Use specific, action-oriented text like "schedule your consultation", "book your session", "get started today"
                
                Generate ONLY the main content (heading + body + CTA). The system will add hook, summary, date, and disclaimer automatically.
            """
            
            print("\nGenerating rewritten content...")
            response = self.text_client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": original_text}
                ],
                temperature=0.7,
            )
            
            # Get the rewritten content
            rewritten_content = response.choices[0].message.content
            
            # Generate summary (2-3 sentences ending with "Read more...")
            print("\nGenerating summary...")
            summary = self._generate_summary(rewritten_content, preserved_sections['hook'])
            
            # Final assembly with template
            print("\nAssembling final article with template...")
            final_content = self._assemble_final_article(preserved_sections['hook'], summary, rewritten_content, preserved_sections['disclaimer'], firm_name, discovery_call_link)
            
            # Validate the generated content using GPT
            components = {
                'keywords': keywords,
                'firm_name': firm_name,
                'location': location,
                'lawyer_name': lawyer_name,
                'city': city,
                'state': state,
                'planning_session_name': planning_session_name,
                'discovery_call_link': discovery_call_link
            }
            
            validation_results = self._validate_with_gpt(original_text, final_content, components)
            
            if validation_results is None:
                print("Warning: Article validation failed. Please review the content manually.")
            
            print("\nArticle generation complete!")
            return final_content
            
        except Exception as e:
            print(f"Error in rewrite_content: {str(e)}")
            return original_text

    def edit_content(self, session_id, user_message, current_content=None):
        if session_id not in self.conversations:
            self.conversations[session_id] = [
                {"role": "system", "content": """
                    You are a legal blog post editor. When the user requests changes:
                    1. The first paragraph should not be repeating and be the same as the original
                    2. The second paragraph should not be extending and be the same as the original
                    3. The last paragraph (disclaimer) should not be repeating and be the same as the original
                    1. Make ONLY the requested changes
                    2. Return the COMPLETE updated blog (not just updated part) in markdown format
                    3. Don't include any commentary or explanations
                    4. Preserve all formatting and structure
                    5. Don't repeat any paragraph meaning no same paragraph should be present.
                """}
            ]
        
        if current_content:
            self.conversations[session_id].append(
                {"role": "assistant", "content": current_content}
            )
        
        self.conversations[session_id].append(
            {"role": "user", "content": user_message}
        )
        
        response = self.text_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=self.conversations[session_id],
            temperature=0.5
        )
        
        ai_response = response.choices[0].message.content
        self.conversations[session_id].append(
            {"role": "assistant", "content": ai_response}
        )
        
        return ai_response
    
    def _validate_and_cleanup_structure(self, content, preserved_sections):
        """Validate and cleanup the article structure to ensure it follows the exact format."""
        try:
            print(f"\n=== VALIDATING AND CLEANING ARTICLE STRUCTURE ===")
            
            paragraphs = content.split('\n\n')
            cleaned_paragraphs = []
            
            # Step 1: Ensure hook is first
            if preserved_sections['hook']:
                cleaned_paragraphs.append(preserved_sections['hook'])
                print("✓ Hook placed at position 1")
            else:
                print("⚠️  No hook found")
            
            # Step 2: Add line break after hook
            cleaned_paragraphs.append("")
            print("✓ Added line break after hook")
            
            # Step 3: Ensure summary is second (2-3 lines)
            if preserved_sections['summary']:
                cleaned_paragraphs.append(preserved_sections['summary'])
                print("✓ Summary placed at position 3")
            else:
                print("⚠️  No summary found")
            
            # Step 4: Add line break after summary
            cleaned_paragraphs.append("")
            print("✓ Added line break after summary")
            
            # Step 5: Add date
            current_date = datetime.now().strftime("%B %d, %Y")
            cleaned_paragraphs.append(f"**Date: {current_date}**")
            print("✓ Added date")
            
            # Step 6: Add line break after date
            cleaned_paragraphs.append("")
            print("✓ Added line break after date")
            
            # Step 7: Find and organize content (heading, article content, CTA)
            cta_found = False
            heading_found = False
            content_paragraphs = []
            
            for i, para in enumerate(paragraphs):
                # Skip if this is the hook or summary (already handled)
                if para.strip() == preserved_sections.get('hook', '').strip():
                    continue
                if para.strip() == preserved_sections.get('summary', '').strip():
                    continue
                
                # Skip any paragraphs that look like they might be hook or summary
                if any(phrase in para.lower() for phrase in ['weekly blog preview', 'read more', 'summary', 'featured article section']):
                    continue
                
                # Skip any paragraphs that are just the hook or summary content
                if para.strip() == preserved_sections.get('hook', '').strip():
                    continue
                if para.strip() == preserved_sections.get('summary', '').strip():
                    continue
                
                # Skip any date paragraphs (we'll add our own date)
                if any(phrase in para.lower() for phrase in ['date:', '**date:', '2025.', '2024.', '2023.']):
                    continue
                
                # Check if this paragraph contains CTA
                cta_phrases = ["Click here to schedule", "Book your Discovery Call", "Schedule your complimentary"]
                if any(phrase in para for phrase in cta_phrases):
                    cta_found = True
                    content_paragraphs.append(para)  # Include the CTA paragraph
                    print(f"✓ Found CTA at paragraph {i+1}")
                    break
                
                # Check if this is a heading (starts with #)
                if para.strip().startswith('#'):
                    if not heading_found:
                        heading_found = True
                        print(f"✓ Found heading at paragraph {i+1}: {para.strip()[:50]}...")
                    content_paragraphs.append(para)
                else:
                    # Add all other content paragraphs
                    content_paragraphs.append(para)
            
            # Add all content paragraphs (including heading and main content)
            cleaned_paragraphs.extend(content_paragraphs)
            
            if not heading_found:
                print("⚠️  No heading found in content")
            if not cta_found:
                print("⚠️  No CTA found in content")
            
            # Step 8: Add disclaimer at the end (only if it exists)
            if preserved_sections['disclaimer']:
                cleaned_paragraphs.append(preserved_sections['disclaimer'])
                print("✓ Disclaimer placed at the end")
            else:
                print("⚠️  No disclaimer found")
            
            # Step 9: DROP EVERYTHING AFTER THE DISCLAIMER
            # The disclaimer should be the final paragraph - no additional content after it
            print("✓ Dropped all content after disclaimer - disclaimer is the final paragraph")
            
            # Clean up any empty paragraphs and ensure proper spacing
            final_paragraphs = []
            for para in cleaned_paragraphs:
                if para.strip():  # Only add non-empty paragraphs
                    final_paragraphs.append(para)
                elif final_paragraphs and final_paragraphs[-1].strip():  # Add empty line only if previous paragraph wasn't empty
                    final_paragraphs.append("")
            
            final_content = '\n\n'.join(final_paragraphs)
            
            print(f"=== STRUCTURE VALIDATION COMPLETE ===")
            print(f"Final structure: Hook → Line Break → Summary → Line Break → Date → Line Break → Heading → Content → CTA → Disclaimer")
            print(f"Total paragraphs: {len(final_paragraphs)}")
            
            return final_content
            
        except Exception as e:
            print(f"Error in structure validation: {str(e)}")
            return content

    def _generate_summary(self, article_content, hook):
        """Generate a 2-3 sentence summary ending with 'Read more...'"""
        try:
            print(f"\n=== GENERATING SUMMARY ===")
            
            summary_prompt = f"""
                Generate a 2-3 sentence summary of this article that:
                1. Is engaging and captures the main point
                2. Ends with "Read more..."
                3. Is different from the hook paragraph
                4. Provides a brief overview of what the article covers
                5. Is written in a professional tone
                
                Hook paragraph: {hook}
                
                Article content: {article_content[:1000]}
                
                Generate ONLY the summary (2-3 sentences ending with "Read more..."). Do not include any other text.
            """
            
            response = self.text_client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a summary generation expert. Always return concise, engaging summaries."},
                    {"role": "user", "content": summary_prompt}
                ],
                temperature=0.7,
            )
            
            summary = response.choices[0].message.content.strip()
            
            # Ensure it ends with "Read more..."
            if not summary.endswith("Read more..."):
                summary = summary.rstrip('.') + ". Read more..."
            
            print(f"✓ Generated summary: {summary[:100]}...")
            print(f"=== SUMMARY GENERATION COMPLETE ===\n")
            
            return summary
            
        except Exception as e:
            print(f"Error generating summary: {str(e)}")
            # Fallback summary
            return "This article explores important considerations for protecting your family's future. Read more..."

    def _clean_article_content(self, article_content):
        """Clean and filter article content to remove unwanted elements"""
        try:
            print(f"\n=== CLEANING ARTICLE CONTENT ===")
            
            if not article_content:
                return ""
            
            # Split into lines for processing
            lines = article_content.split('\n')
            cleaned_lines = []
            
            # Filter out unwanted content
            skip_until_heading = True
            
            for line in lines:
                line = line.strip()
                
                # Skip empty lines
                if not line:
                    continue
                
                # Skip preview/summary text
                if any(phrase in line.lower() for phrase in [
                    'weekly blog preview',
                    'summary you can use',
                    'featured article section',
                    'email newsletter',
                    'preview/summary'
                ]):
                    print(f"✓ Skipped preview text: {line[:50]}...")
                    continue
                
                # Skip any date lines (we'll add our own)
                if any(phrase in line.lower() for phrase in [
                    'date:', '**date:', '2025.', '2024.', '2023.'
                ]):
                    print(f"✓ Skipped date line: {line[:50]}...")
                    continue
                
                # Skip hook and summary content if they appear in the middle
                if 'read more...' in line.lower() and len(line) < 200:
                    print(f"✓ Skipped duplicate summary: {line[:50]}...")
                    continue
                
                # Look for the main heading (should start with #)
                if line.startswith('#'):
                    skip_until_heading = False
                    print(f"✓ Found heading: {line[:50]}...")
                elif skip_until_heading and (
                    # Look for title-like content (longer lines that seem like titles)
                    (len(line) > 20 and len(line) < 100 and 
                     any(word in line.lower() for word in ['mail carrier', 'pet', 'trust', 'planning', 'legacy', 'estate', 'understanding', 'how', 'why', 'what', 'when', 'where', 'guide', 'complete', 'essential', 'important', 'protect', 'secure', 'plan', 'future', 'family', 'legal', 'law', 'attorney', 'lawyer']) and
                     not any(phrase in line.lower() for phrase in ['read more', 'summary', 'preview', 'date:', '**date:'])
                    )
                ):
                    skip_until_heading = False
                    # Ensure proper heading format
                    line = f"# {line}"
                    print(f"✓ Found heading: {line[:50]}...")
                
                # Only add lines after we've found the heading
                if not skip_until_heading:
                    cleaned_lines.append(line)
            
            # Join lines back together with proper spacing
            cleaned_content = '\n\n'.join(cleaned_lines)
            
            print(f"✓ Content cleaned successfully")
            print(f"=== CONTENT CLEANING COMPLETE ===\n")
            
            return cleaned_content
            
        except Exception as e:
            print(f"Error cleaning article content: {str(e)}")
            return article_content

    def _assemble_final_article(self, hook, summary, article_content, disclaimer, firm_name="", discovery_call_link=""):
        """Assemble the final article using external template file"""
        try:
            print(f"\n=== ASSEMBLING FINAL ARTICLE WITH EXTERNAL TEMPLATE ===")
            
            # Get current date
            current_date = datetime.now().strftime("%B %d, %Y")
            
            # Clean and filter the article content to remove any unwanted elements
            cleaned_content = self._clean_article_content(article_content)
            
            # Read the external template file
            template_path = os.path.join(Config.ARTICLES_DIR, 'template.md')
            try:
                with open(template_path, 'r', encoding='utf-8') as f:
                    template_content = f.read()
                print("✓ External template loaded successfully")
            except FileNotFoundError:
                print("⚠️  Template file not found, using fallback template")
                template_content = """Weekly blog preview/summary you can use on your main blog page and Featured Article section of your email newsletter:

{summary of the article}

**Date: {current_date}**
{newly generated Title with proper markdown formatting}

{newly generated content with proper markdown formatting}

*###### This article is a service of [ name ], a Personal Family Lawyer® Firm. We don't just draft documents; we ensure you make informed and empowered decisions about life and death, for yourself and the people you love. That's why we offer a Life & Legacy Planning® Session, during which you will get more financially organized than you've ever been before and make all the best choices for the people you love. You can begin by calling our office today to schedule a Life & Legacy Planning Session.*

The content is sourced from Personal Family Lawyer® for use by Personal Family Lawyer firms, a source believed to be providing accurate information. This material was created for educational and informational purposes only and is not intended as ERISA, tax, legal, or investment advice. If you are seeking legal advice specific to your needs, such advice services must be obtained on your own separate from this educational material."""
            
            # Replace placeholders in the template
            final_content = template_content.replace('{summary of the article}', summary.strip() if summary else '')
            final_content = final_content.replace('{current_date}', current_date)
            final_content = final_content.replace('{newly generated Title with proper markdown formatting}', '')
            final_content = final_content.replace('{newly generated content with proper markdown formatting}', cleaned_content if cleaned_content else '')
            final_content = final_content.replace('{firm_name}', firm_name if firm_name else '[Firm Name]')
            final_content = final_content.replace('{discovery_call_link}', discovery_call_link if discovery_call_link else '#')
            
            # Remove the preview text line if no hook is provided
            if not hook or not hook.strip():
                lines = final_content.split('\n')
                # Remove the first line (preview text) and any empty lines after it
                if lines and 'Weekly blog preview/summary' in lines[0]:
                    lines = lines[1:]  # Remove first line
                    # Remove empty lines after the removed line
                    while lines and not lines[0].strip():
                        lines = lines[1:]
                final_content = '\n'.join(lines)
            
            print(f"✓ Article assembled using external template")
            print(f"=== EXTERNAL TEMPLATE ASSEMBLY COMPLETE ===\n")
            
            return final_content
            
        except Exception as e:
            print(f"Error assembling final article: {str(e)}")
            return article_content

    def _format_markdown(self, content):
        """Apply final markdown formatting to ensure proper structure and formatting."""
        try:
            print(f"\n=== APPLYING FINAL MARKDOWN FORMATTING ===")
            
            # Extract the preserved sections first
            preserved_sections = self._extract_sections(content)
            
            formatting_prompt = f"""
                You are a markdown formatting expert. Format the following article content to ensure proper markdown structure and formatting.
                
                CRITICAL: DO NOT MODIFY THESE PRESERVED SECTIONS:
                - Hook: "{preserved_sections.get('hook', '')}"
                - Summary: "{preserved_sections.get('summary', '')}"
                - Disclaimer: "{preserved_sections.get('disclaimer', '')}"
                
                REQUIREMENTS:
                1. DO NOT change the hook, summary, or disclaimer content - keep them exactly as they are
                2. DO NOT move, modify, or reorder the hook, summary, or disclaimer sections
                3. Ensure all headings start with # (main heading), ## (subheadings), or ### (sub-subheadings)
                4. Ensure proper line breaks between sections (use double line breaks)
                5. Format bold text with **text**
                6. Format italic text with *text*
                7. Ensure bullet points use - or * with proper spacing
                8. Ensure the date is properly formatted as **Date: Month DD, YYYY**
                9. Maintain the exact structure: Hook → Line Break → Summary → Line Break → Date → Line Break → Heading → Content → CTA → Line Break → Disclaimer
                10. Do not change the content, only improve the formatting
                11. Ensure proper spacing between paragraphs
                12. Make sure the heading (title) is properly formatted with # at the beginning
                13. Ensure the date line is properly formatted with **Date: Month DD, YYYY**
                14. Add proper line breaks between all sections
                
                CONTENT TO FORMAT:
                {content}
                
                Return ONLY the formatted content with proper markdown formatting. Do not add any explanations or additional text.
            """
            
            response = self.text_client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {"role": "system", "content": "You are a markdown formatting expert. Always return properly formatted markdown content."},
                    {"role": "user", "content": formatting_prompt}
                ],
                temperature=0.1,  # Low temperature for consistent formatting
            )
            
            formatted_content = response.choices[0].message.content.strip()
            
            # Validate that preserved sections are still in their correct positions
            print("Validating preserved sections after formatting...")
            final_content = self._validate_and_cleanup_structure(formatted_content, preserved_sections)
            
            print("✓ Markdown formatting applied successfully")
            print(f"=== MARKDOWN FORMATTING COMPLETE ===\n")
            
            return final_content
            
        except Exception as e:
            print(f"Error in markdown formatting: {str(e)}")
            print("Returning original content without markdown formatting")
            return content

class ImageGenerator:
    def __init__(self):
        self.image_client = AzureOpenAI(
            api_key=os.getenv("AZURE_DALLE_KEY"),
            api_version="2024-02-01",
            azure_endpoint=os.getenv("AZURE_DALLE_ENDPOINT")
        )
        self.text_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            api_version="2024-02-15-preview",
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )

    def generate_image(self, text_prompt):
        try:
            safe_prompt = self._get_safe_image_prompt(text_prompt)
            
            response = self.image_client.images.generate(
                model=os.getenv("AZURE_DALLE_DEPLOYMENT"),
                prompt=safe_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            os.makedirs(os.path.join(app.static_folder, 'generated'), exist_ok=True)
            
            timestamp = int(time.time())
            image_filename = f"image_{timestamp}.png"
            image_path = os.path.join(app.static_folder, 'generated', image_filename)
            
            response = requests.get(image_url)
            with open(image_path, 'wb') as f:
                f.write(response.content)
            
            return image_filename
            
        except Exception as e:
            print(f"Image generation failed: {e}")
            return None
        
    def _get_safe_image_prompt(self, text_prompt):
        response = self.text_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": """
                    You are a creative prompt engineer for legal blog images. Create safe and professional image prompts that:
                    1. Are directly relevant to the blog content
                    2. Be 'unique to the blog's content', not generic or reusable for any legal article
                    3. Reflect the main topic, themes, or message of the blog post
                    4. Focus on modern, visually appealing representations
                    5. Must pass Azure content filters
                    6. Avoids sensitive content
                    The prompt should be detailed and specific, including:
                        - Main subject
                        - Style description
                        - Color palette
                        - Composition notes
                        - Mood/tone
                    - Is based on this blog content:
                """},
                {"role": "user", "content": text_prompt[:1000]}
            ],
            temperature=1
        )
        return response.choices[0].message.content

class FileManager:
    @staticmethod
    def list_articles():
        """
        List all DOCX files in the articles directory
        Returns:
            List of article filenames
        """
        articles = [f for f in os.listdir(Config.ARTICLES_DIR) if f.endswith('.docx')]
        return articles
    
    @staticmethod
    def get_article_metadata():
        """
        Read and parse the metadata.json file
        Returns:
            Dictionary of article metadata
        """
        metadata_path = os.path.join(Config.ARTICLES_DIR, 'metadata.json')
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                content = f.read()
                metadata = json.loads(content)
                # Convert list to dictionary for easier lookup
                result = {article['filename']: article for article in metadata['articles']}
                return result
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            print(f"Error reading metadata: {str(e)}")
            return {}
    
    @staticmethod
    def read_docx(filename):
        """
        Read content from a DOCX file
        Args:
            filename: Name of the DOCX file (may be URL-encoded)
        Returns:
            Extracted text content
        """
        # URL-decode the filename first
        decoded_filename = unquote(filename)
        
        # For article filenames, we need to be more permissive
        # Check if the file exists in the articles directory
        filepath = os.path.join(Config.ARTICLES_DIR, decoded_filename)
        
        # Normalize the path to prevent path traversal
        normalized_path = os.path.normpath(filepath)
        
        # Simple path traversal check - look for .. in the path
        if '..' in normalized_path:
            raise ValueError("Path traversal detected")
        
        # Check if file exists
        if not os.path.exists(normalized_path):
            raise FileNotFoundError(f"Article file not found: {decoded_filename}")
        
        doc = Document(normalized_path)
        return "\n".join([para.text for para in doc.paragraphs])

    @staticmethod
    def read_markdown(filename):
        """
        Read content from a markdown file
        Args:
            filename: Name of the markdown file (may be URL-encoded)
        Returns:
            Markdown content
        """
        # URL-decode the filename first
        decoded_filename = unquote(filename)
        
        # Convert .docx extension to .md extension
        if decoded_filename.endswith('.docx'):
            markdown_filename = decoded_filename.replace('.docx', '.md')
        else:
            markdown_filename = decoded_filename
        
        # Check if the file exists in the articles directory
        filepath = os.path.join(Config.ARTICLES_DIR, markdown_filename)
        
        # Normalize the path to prevent path traversal
        normalized_path = os.path.normpath(filepath)
        
        # Simple path traversal check - look for .. in the path
        if '..' in normalized_path:
            raise ValueError("Path traversal detected")
        
        # Check if file exists
        if not os.path.exists(normalized_path):
            raise FileNotFoundError(f"Markdown file not found: {markdown_filename}")
        
        with open(normalized_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    @staticmethod
    def save_content(content):
        """
        Save generated content to a file
        Args:
            content: Content to save
        Returns:
            Filename of the saved content
        """
        filename = f"blog_{int(time.time())}.txt"
        path = os.path.join(Config.GENERATED_DIR, filename)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return filename

    @staticmethod
    def generate_formatted_docx(content, title="Legal Blog"):
        """Generate DOCX with exact formatting from markdown"""
        doc = Document()

        # Custom styles (can be modified)
        styles = {
            'h1': {'font_size': 16, 'bold': True, 'color': RGBColor(0, 32, 96)},
            'h2': {'font_size': 14, 'bold': True, 'color': RGBColor(0, 64, 128)},
            'h3': {'font_size': 12, 'bold': True, 'italic': True},
            'bold': {'bold': True},
            'normal': {'font_size': 11}
        }
        
        def apply_style(run, style):
            """Helper function to apply formatting"""
            run.font.size = Pt(style.get('font_size', 11))
            run.font.bold = style.get('bold', False)
            run.font.italic = style.get('italic', False)
            if 'color' in style:
                run.font.color.rgb = style['color']
        
        # Process markdown content line by line
        lines = content.split('\n')
        for line in lines:

            if line.replace('-', '').strip() == '' and len(line) >= 3:
                continue

            # Detect formatting
            if line.startswith('# '):  # H1
                para = doc.add_heading(level=1)
                run = para.add_run(line[2:].strip())
                apply_style(run, styles['h1'])
                
            elif line.startswith('## '):  # H2
                para = doc.add_heading(level=2)
                run = para.add_run(line[3:].strip())
                apply_style(run, styles['h2'])
                
            elif line.startswith('### '):  # H3
                para = doc.add_heading(level=3)
                run = para.add_run(line[4:].strip())
                apply_style(run, styles['h3'])
                
            elif '**' in line:  # Bold text
                para = doc.add_paragraph()
                parts = re.split(r'(\*\*.+?\*\*)', line)
                for part in parts:
                    if part.startswith('**') and part.endswith('**'):
                        run = para.add_run(part[2:-2])
                        apply_style(run, styles['bold'])
                    else:
                        para.add_run(part)
            
            else:  # Normal paragraph
                para = doc.add_paragraph()
                run = para.add_run(line)
                apply_style(run, styles['normal'])
        # Collect all empty paragraphs
        empty_paragraphs = [p for p in doc.paragraphs if not p.text.strip()]

        # Remove each empty paragraph from the document
        for p in empty_paragraphs:
            p._element.getparent().remove(p._element)

        # Save to bytes buffer
        file_stream = BytesIO()
        doc.save(file_stream)
        file_stream.seek(0)
        return file_stream

azure_services = AzureServices()
image_generator = ImageGenerator()

@app.template_filter('markdown')
def markdown_filter(text):
    html = markdown.markdown(text)
    soup = BeautifulSoup(html, 'html.parser')
    return str(soup)

@app.route('/')
def home():
    if not UserSession.get_current_user():
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        firm = request.form['firm']
        location = request.form['location']
        lawyer_name = request.form['lawyer_name']
        state = request.form['state']
        address = request.form.get('address', '')
        planning_session = request.form.get('planning_session', '')
        other_planning_session = request.form.get('other_planning_session', '')
        discovery_call_link = request.form.get('discovery_call_link', '')

        if UserSession.register(email, password, firm, location, lawyer_name, state, 
                              address, planning_session, other_planning_session, discovery_call_link):
            # Auto-login after registration
            UserSession.login(email, password)
            return redirect(url_for('dashboard'))
        
        return render_template('register.html', error="Email already registered")
    
    return render_template('register.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    user = UserSession.get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Handle both form data and JSON requests
        if request.is_json:
            data = request.get_json()
            firm = data.get('firm', '')
            location = data.get('location', '')
            lawyer_name = data.get('lawyer_name', '')
            state = data.get('state', '')
            address = data.get('address', '')
            planning_session = data.get('planning_session', '')
            discovery_call_link = data.get('discovery_call_link', '')
            selected_tone = data.get('selected_tone', '')
            tone_description = data.get('tone_description', '')
            keywords = data.get('keywords', '')
        else:
            firm = request.form['firm']
            location = request.form['location']
            lawyer_name = request.form['lawyer_name']
            state = request.form['state']
            address = request.form.get('address', '')
            planning_session = request.form.get('planning_session', '')
            discovery_call_link = request.form.get('discovery_call_link', '')
            selected_tone = request.form.get('selected_tone', '')
            tone_description = request.form.get('tone_description', '')
            keywords = request.form.get('keywords', '')
        
        if UserSession.update_profile(user['username'], firm, location, lawyer_name, state, address, planning_session, "", discovery_call_link, selected_tone, tone_description, keywords):
            session['user']['firm'] = firm
            session['user']['location'] = location
            session['user']['lawyer_name'] = lawyer_name
            session['user']['state'] = state
            session['user']['address'] = address
            session['user']['planning_session'] = planning_session
            session['user']['discovery_call_link'] = discovery_call_link
            session['user']['selected_tone'] = selected_tone
            session['user']['tone_description'] = tone_description
            session['user']['keywords'] = keywords
            session.modified = True
            
            # Return JSON response for AJAX requests
            if request.is_json:
                return jsonify({
                    'success': True,
                    'firm': firm,
                    'location': location,
                    'lawyer_name': lawyer_name,
                    'state': state,
                    'address': address,
                    'planning_session': planning_session,
                    'discovery_call_link': discovery_call_link,
                    'selected_tone': selected_tone,
                    'tone_description': tone_description,
                    'keywords': keywords
                })
            
            return redirect(url_for('dashboard'))
        
        # Return JSON response for AJAX requests
        if request.is_json:
            return jsonify({'success': False, 'error': 'Update failed'}), 400
        
        return render_template('profile.html', error="Update failed", user=session['user'])
    
    return render_template('profile.html', user=session['user'])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if UserSession.login(request.form['email'], request.form['password']):
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid credentials")
    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        
        # Check if user exists
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        
        if user:
            # Generate reset token
            token = secrets.token_urlsafe(32)
            expires = datetime.now() + timedelta(hours=24)
            
            # Store reset token in database (SQL Server compatible)
            # First, delete any existing tokens for this email
            db.execute('DELETE FROM password_resets WHERE email = ?', (email,))
            
            # Then insert the new token
            db.execute('''
                INSERT INTO password_resets (email, token, expires)
                VALUES (?, ?, ?)
            ''', (email, token, expires))
            db.commit()
            
            # In a real application, you would send an email here
            # For now, we'll just show a success message with the token
            reset_url = url_for('reset_password', token=token, _external=True)
            
            return render_template('forgot_password.html', 
                                 success=f"Password reset link sent! For demo purposes, here's the link: {reset_url}")
        else:
            return render_template('forgot_password.html', 
                                 error="If an account with that email exists, a reset link has been sent.")
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    db = get_db()
    
    # Check if token is valid and not expired
    reset_record = db.execute('''
        SELECT * FROM password_resets 
        WHERE token = ? AND expires > ? AND used = 0
    ''', (token, datetime.now())).fetchone()
    
    if not reset_record:
        return render_template('reset_password.html', token=token,
                             error="Invalid or expired reset link. Please request a new one.")
    
    if request.method == 'POST':
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            return render_template('reset_password.html', token=token,
                                 error="Passwords do not match.")
        
        if len(password) < 6:
            return render_template('reset_password.html', token=token,
                                 error="Password must be at least 6 characters long.")
        
        # Update user password - store as plain text
        db.execute('UPDATE users SET password = ? WHERE email = ?', 
                  (password, reset_record[1]))
        
        # Mark token as used
        db.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
        db.commit()
        
        return render_template('reset_password.html', token=token,
                             success="Password reset successfully! You can now login with your new password.")
    
    return render_template('reset_password.html', token=token)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    user = UserSession.get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    # Get articles and their metadata
    articles = FileManager.list_articles()
    metadata = FileManager.get_article_metadata()
    
    # Get unique series names
    series_list = set()
    for article in articles:
        meta = metadata.get(article, {})
        if 'series' in meta:
            series_list.add(meta['series'])
    series_list = sorted(series_list) if series_list else None

    # Combine standard tones with user's custom tones
    standard_tones = [
        ('Professional', 'Formal and business-like tone suitable for corporate audiences'),
        ('Friendly', 'Warm and approachable tone that builds rapport with readers'),
        ('Educational', 'Clear and informative tone designed to explain concepts')
    ]
    
    # Get user's custom tones from database
    custom_tones = UserSession.get_custom_tones(user['id'])
    all_tones = standard_tones + [(t['name'], t['description']) for t in custom_tones]
    
    # Convert to the format expected by the template
    tone_options = [t[0] for t in all_tones]
    tone_descriptions = {t[0]: t[1] for t in all_tones}
    
    return render_template('dashboard.html', 
                         user=user,
                         username=user['username'],
                         articles=articles,
                         metadata=metadata,
                         tone_options=tone_options,
                         tone_descriptions=tone_descriptions,
                         user_keywords=user.get('keywords', ''),
                         series_list=series_list)

@app.route('/add_tone', methods=['POST'])
def add_tone():
    user = UserSession.get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401
    
    data = request.get_json() if request.is_json else request.form
    tone_name = data.get('tone_name', '').strip()
    tone_description = data.get('tone_description', '').strip()
    
    if not tone_name:
        return jsonify({'success': False, 'error': 'Tone name is required'}), 400
    
    if UserSession.add_custom_tone(user['id'], tone_name, tone_description):
        return jsonify({
            'success': True,
            'tone_name': tone_name,
            'tone_description': tone_description
        })
    
    return jsonify({'success': False, 'error': 'Tone with this name already exists'}), 400

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'User not authenticated'})
    
    try:
        message = request.form.get('message')
        contact_email = request.form.get('contact_email')
        
        # Validate required fields
        if not message:
            return jsonify({'success': False, 'message': 'Please provide a message'})
        
        # Set default values for removed fields
        feedback_type = 'general'
        priority = 'medium'
        subject = 'User Feedback'
        
        # Submit feedback using UserSession method
        if UserSession.submit_feedback(session['user']['id'], feedback_type, priority, subject, message, contact_email):
            return jsonify({'success': True, 'message': 'Feedback submitted successfully'})
        else:
            return jsonify({'success': False, 'message': 'An error occurred while submitting feedback'})
        
    except Exception as e:
        print(f"Error submitting feedback: {str(e)}")
        return jsonify({'success': False, 'message': 'An error occurred while submitting feedback'})

@app.route('/select/<article>', methods=['GET', 'POST'])
def select_article(article):
    user = UserSession.get_current_user()
    if not user:
        return redirect(url_for('login'))
    
    # Initialize variables that will be used in both GET and POST
    firm = ''
    location = ''
    
    if request.method == 'POST':
        # Use user's saved tone and keywords from their profile
        tone = user.get('selected_tone', 'Professional')
        tone_description = user.get('tone_description', '')
        
        # If no custom tone description is saved, use default descriptions
        if not tone_description:
            default_descriptions = {
                'Professional': 'Formal and business-like tone suitable for corporate audiences',
                'Friendly': 'Warm and approachable tone that builds rapport with readers',
                'Educational': 'Clear and informative tone designed to explain concepts'
            }
            tone_description = default_descriptions.get(tone, 'Formal and business-like tone suitable for corporate audiences')
            
        keywords = user.get('keywords', '')
        firm = user.get('firm', '')
        location = user.get('location', '')
        lawyer_name = user.get('lawyer_name', '')
        city = user.get('location', '')
        state = user.get('state', '')
        planning_session_name = user.get('planning_session', '15-minute discovery call')
        discovery_call_link = user.get('discovery_call_link', '')

        # Generate the blog post with the selected tone
        blog_content = azure_services.rewrite_content(
            FileManager.read_docx(article),
            tone,
            tone_description,
            keywords,
            firm,
            location,
            lawyer_name,
            city,
            state,
            planning_session_name,
            discovery_call_link
        )
        
        # Save the generated content to a file
        filename = FileManager.save_content(blog_content)
        
        # Set up the session data for the review page (without image initially)
        session['current_post'] = {
            'original': article,
            'content': blog_content,
            'image': None,  # Image will be generated later when requested
            'created': datetime.now().strftime("%Y-%m-%d %H:%M"),
            'tone': tone,
            'filename': filename
        }
        
        # Initialize chat history
        session['chat_history'] = [{
            'role': 'assistant',
            'content': blog_content,
            'content_is_blog': True,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }]
        
        # Generate a unique session ID for the chat
        session['session_id'] = os.urandom(16).hex()
        
        return redirect(url_for('review'))
    
    tone_options = [
        'Professional',
        'Friendly',
        'Educational'
    ]
    
    tone_descriptions = {
        'Professional': 'Formal and business-like tone suitable for corporate audiences',
        'Friendly': 'Warm and approachable tone that builds rapport with readers',
        'Educational': 'Clear and informative tone designed to explain concepts'
    }
    
    return render_template('select.html',
                         article_name=article,
                         tone_options=tone_options,
                         tone_descriptions=tone_descriptions,
                         firm=firm,
                         location=location)

@app.route('/use_version', methods=['POST'])
def use_version():
    if 'current_post' not in session:
        return redirect(url_for('dashboard'))
    
    selected_content = request.form['content']
    
    session['current_post']['content'] = selected_content
    session.modified = True
    
    return redirect(url_for('finalize'))

@app.route('/finalize')
def finalize():
    if 'current_post' not in session:
        return redirect(url_for('dashboard'))
    
    post = session['current_post']
    filename = FileManager.save_content(post['content'])
    image_url = url_for('static', filename=f'generated/{post["image"]}') if post.get('image') else None
    
    return render_template('finalize.html', 
                         post=post,
                         filename=filename,
                         image_url=image_url)

@app.route('/review', methods=['GET', 'POST'])
def review():
    # Check if we have a filename parameter but no current_post in session
    filename = request.args.get('filename')
    if filename and 'current_post' not in session:
        # Try to load the content from the file
        try:
            # Use safe path validation
            filepath = get_safe_file_path(Config.GENERATED_DIR, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Set up the session data
            session['current_post'] = {
                'content': content,
                'filename': filename,
                'created': datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            
            # Initialize chat history
            session['chat_history'] = [{
                'role': 'assistant',
                'content': content,
                'content_is_blog': True,
                'timestamp': datetime.now().strftime("%H:%M:%S")
            }]
            
            # Generate a unique session ID for the chat
            session['session_id'] = os.urandom(16).hex()
        except (ValueError, FileNotFoundError) as e:
            print(f"Error loading file: {e}")
            return redirect(url_for('dashboard'))
        except Exception as e:
            print(f"Error loading file: {e}")
            return redirect(url_for('dashboard'))
    
    # If we still don't have current_post in session, redirect to dashboard
    if 'current_post' not in session:
        return redirect(url_for('dashboard'))
    
    post = session['current_post']
    
    if 'session_id' not in session:
        session['session_id'] = os.urandom(16).hex()
    
    if 'chat_history' not in session:
        session['chat_history'] = [{
            'role': 'assistant',
            'content': post['content'],
            'content_is_blog': True,
            'timestamp': datetime.now().strftime("%H:%M:%S")
        }]
    
    if request.method == 'POST':
        if 'edit_message' in request.form:  # Chat-style editing
            user_message = request.form['edit_message']
            
            current_content = next(
                (msg['content'] for msg in reversed(session['chat_history']) 
                 if msg['content_is_blog']),
                post['content']
            )
            
            edited_content = azure_services.edit_content(
                session['session_id'],
                user_message,
                current_content
            )
            
            session['chat_history'].append({
                'role': 'user',
                'content': user_message,
                'content_is_blog': False,
                'timestamp': datetime.now().strftime("%H:%M:%S")
            })
            session['chat_history'].append({
                'role': 'assistant',
                'content': edited_content,
                'content_is_blog': True,
                'timestamp': datetime.now().strftime("%H:%M:%S")
            })
            
            post['content'] = edited_content
            session['current_post'] = post
            
        elif 'content' in request.form:  # Manual editing
            post['content'] = request.form['content']
            session['current_post'] = post
            session['chat_history'].append({
                'role': 'assistant',
                'content': post['content'],
                'content_is_blog': True,
                'timestamp': datetime.now().strftime("%H:%M:%S")
            })

        session.modified = True
        return redirect(url_for('review'))
    
    # Save the current content to a file and get the filename
    if 'filename' not in post:
        filename = FileManager.save_content(post['content'])
        post['filename'] = filename
        session['current_post'] = post
    
    # Get source article content if available
    source_article_content = None
    if 'original' in post:
        try:
            markdown_content = FileManager.read_markdown(post['original'])
            # Convert markdown to HTML for proper display
            source_article_content = markdown.markdown(markdown_content)
        except Exception as e:
            print(f"Error reading source article: {e}")
            source_article_content = "Source article not available"
    
    image_url = url_for('static', filename=f'generated/{post["image"]}') if post.get('image') else None
    
    return render_template('review.html', 
                         post=post,
                         chat_history=session['chat_history'],
                         source_article_content=source_article_content,
                         image_url=image_url)

@app.route('/save_changes', methods=['POST'])
def save_changes():
    if 'current_post' not in session:
        return redirect(url_for('dashboard'))
    
    edited_content = request.form.get('content', '')
    
    session['current_post']['content'] = edited_content
    
    if 'chat_history' not in session:
        session['chat_history'] = []
    
    session['chat_history'].append({
        'role': 'system',
        'content': 'User saved manual changes',
        'content_is_blog': False,
        'timestamp': datetime.now().strftime("%H:%M:%S")
    })
    
    session.modified = True
    return redirect(url_for('finalize'))

@app.route('/download/<filename>')
def download(filename):
    if 'current_post' not in session:
        return redirect(url_for('dashboard'))
    
    try:
        # For generated files, use simple path validation since they're internally generated
        filepath = os.path.join(Config.GENERATED_DIR, filename)
        normalized_path = os.path.normpath(filepath)
        
        # Simple path traversal check - look for .. in the path
        if '..' in normalized_path:
            print(f"Path traversal detected: {normalized_path}")
            return redirect(url_for('review'))
        
        # Check if file exists
        if not os.path.exists(normalized_path):
            print(f"File not found: {normalized_path}")
            return redirect(url_for('review'))
        
        with open(normalized_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Get title
        title = session['current_post'].get('original', 'Legal Blog').replace('.docx', '')
        
        # Generate formatted DOCX
        docx_file = FileManager.generate_formatted_docx(content, title)
        
        return send_file(
            docx_file,
            as_attachment=True,
            download_name=f"{title}.docx",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
    except Exception as e:
        print(f"Download error: {e}")
        return redirect(url_for('review'))

@app.route('/generate_image')
async def generate_image():
    if 'current_post' not in session:
        return redirect(url_for('dashboard'))

    # Call Azure Function for image generation
    function_url = f"{FUNCTION_APP_URL}/api/image_generator?code={FUNCTION_KEY}"
    payload = {
        "text_prompt": session['current_post']['content']
    }
    if SIMULATE_OPENAI:
        await simulate_openai_call()
        session['current_post']['image'] = "dummy.png"
        session.modified = True
        return redirect(url_for('review'))
    
    import aiohttp, base64, os
    async with aiohttp.ClientSession() as client_session:
        async with client_session.post(function_url, json=payload) as response:
            if response.status != 200:
                raise Exception(f"Function error: {await response.text()}")
            result = await response.json()
    
    image_filename = result["image_filename"]
    os.makedirs(os.path.join(app.static_folder, 'generated'), exist_ok=True)
    
    # Save the image data to file
    image_path = os.path.join(app.static_folder, 'generated', image_filename)
    with open(image_path, 'wb') as f:
        f.write(base64.b64decode(result["image_data"]))

    if image_filename:
        session['current_post']['image'] = image_filename
        session.modified = True
    
    return redirect(url_for('review'))
    
@app.teardown_appcontext
def teardown_db(exception):
    close_db()

@app.route('/preview_article/<article>')
def preview_article(article):
    try:
        # URL-decode the article filename first
        decoded_article = unquote(article)
        
        # For article filenames, we need to be more permissive
        # Check if the file exists in the articles directory
        article_path = os.path.join(Config.ARTICLES_DIR, decoded_article)
        normalized_article_path = os.path.normpath(article_path)
        
        # Simple path traversal check - look for .. in the path
        if '..' in normalized_article_path:
            return jsonify({'error': 'Invalid article path'}), 400
        
        # Try to read markdown file first
        markdown_filename = decoded_article.replace('.docx', '.md')
        markdown_path = os.path.join(Config.ARTICLES_DIR, markdown_filename)
        normalized_markdown_path = os.path.normpath(markdown_path)
        
        # Ensure markdown path is also safe
        if '..' in normalized_markdown_path:
            return jsonify({'error': 'Invalid markdown path'}), 400
        
        if os.path.exists(normalized_markdown_path):
            # Read the markdown content
            with open(normalized_markdown_path, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            # If markdown doesn't exist, read from docx
            if not os.path.exists(normalized_article_path):
                return jsonify({'error': 'Article not found'}), 404
                
            doc = Document(normalized_article_path)
            content = "\n".join([para.text for para in doc.paragraphs])
            
        # Convert the content to HTML for preview
        html_content = markdown.markdown(content)
        return jsonify({'content': html_content})
    except (ValueError, FileNotFoundError) as e:
        print(f"File access error in preview_article: {str(e)}")
        return jsonify({'error': 'Article not found'}), 404
    except Exception as e:
        print(f"Error in preview_article: {str(e)}")  # Add logging
        return jsonify({'error': str(e)}), 500

def is_safe_filename(filename):
    """Validate that filename is safe and doesn't contain path traversal characters"""
    if not filename:
        return False
    
    # Check for path traversal characters
    dangerous_chars = ['..', '/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in dangerous_chars:
        if char in filename:
            return False
    
    # Check if filename is only alphanumeric, dots, hyphens, and underscores
    if not re.match(r'^[a-zA-Z0-9._-]+$', filename):
        return False
    
    return True

def get_safe_file_path(base_dir, filename):
    """Safely construct a file path within the base directory"""
    if not is_safe_filename(filename):
        raise ValueError("Invalid filename")
    
    # Normalize the path to prevent path traversal
    full_path = os.path.normpath(os.path.join(base_dir, filename))
    
    # Ensure the path is within the base directory
    if not full_path.startswith(os.path.abspath(base_dir)):
        raise ValueError("Path traversal detected")
    
    return full_path

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)