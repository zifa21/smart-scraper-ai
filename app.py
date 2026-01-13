import streamlit as st
import os
import json
import asyncio
import pandas as pd
import subprocess
import sys

# Configuration de la page
st.set_page_config(page_title="Smart Scraper AI", page_icon="🛒", layout="wide")

# Installation de Playwright si nécessaire (pour le déploiement Cloud)
@st.cache_resource
def install_playwright():
        try:
                    import playwright
except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])

    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install-deps"])

install_playwright()

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from openai import OpenAI
import requests
from datetime import datetime

# Initialisation de l'IA
client = OpenAI()

class SmartScraper:
        def __init__(self):
                    self.history_file = "scraping_history.json"
                    if 'history' not in st.session_state:
                                    st.session_state.history = self.load_history()

                def load_history(self):
                            if os.path.exists(self.history_file):
                                            try:
                                                                with open(self.history_file, 'r') as f:
                                                                                        return json.load(f)
                                                                                except:
                                                                return []
                                        return []

    def save_to_history(self, products):
                for p in products:
                                if not any(h.get('name') == p.get('name') and h.get('price') == p.get('price') for h in st.session_state.history):
                                                    p['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                    st.session_state.history.append(p)
                                            with open(self.history_file, 'w') as f:
                                                            json.dump(st.session_state.history, f, indent=4)

    async def detect_and_fetch(self, url):
                try:
                                resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
            is_static = len(resp.text) > 1000
        except:
            is_static = False

        async with async_playwright() as p:
                        browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                  
