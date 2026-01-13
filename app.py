import streamlit as st
import os
import json
import asyncio
import pandas as pd
import subprocess
import sys
import google.generativeai as genai

# Configuration de la page
st.set_page_config(page_title="Smart Scraper AI (Gemini)", page_icon="🛒", layout="wide")

# Installation de Playwright si nécessaire
@st.cache_resource
def install_playwright():
    try:
        import playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])

install_playwright()

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests
from datetime import datetime

# Initialisation de Gemini
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash') # Utilisation de la version Flash
else:
    st.error("Veuillez configurer GEMINI_API_KEY dans les Secrets de Streamlit.")

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
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(2)
                content = await page.content()
                await browser.close()
                return content
            except:
                await browser.close()
                return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        for s in soup(["script", "style", "svg", "path", "footer", "nav", "header"]):
            s.decompose()
        return soup.prettify()[:30000]

    async def analyze_with_gemini(self, html_snippet):
        prompt = f"""
        Analyse ce code HTML e-commerce et extrais les produits.
        HTML: {html_snippet}
        
        Retourne UNIQUEMENT un JSON valide (liste d'objets) avec:
        - name: nom du produit
        - price: prix
        - brand: marque
        - ean: code EAN/GTIN (cherche bien)
        - image_url: lien image
        - product_url: lien produit
        """
        try:
            response = model.generate_content(prompt)
            # Nettoyage de la réponse pour extraire le JSON
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            return json.loads(text)
        except Exception as e:
            st.error(f"Erreur Gemini: {e}")
            return []

# Interface
st.title("🚀 Smart Scraper AI (Gemini 2.5 Flash)")

url_input = st.text_input("URL du site à scraper")

if st.button("Lancer le Scraping"):
    if not api_key:
        st.error("Clé API manquante.")
    elif url_input:
        scraper = SmartScraper()
        with st.spinner("Scraping en cours avec Gemini..."):
            html = asyncio.run(scraper.detect_and_fetch(url_input))
            if html:
                clean = scraper.clean_html(html)
                products = asyncio.run(scraper.analyze_with_gemini(clean))
                if products:
                    df = pd.DataFrame(products)
                    st.dataframe(df)
                    st.download_button("Télécharger CSV", df.to_csv(index=False), "data.csv")
                else:
                    st.warning("Aucun produit trouvé.")
            else:
                st.error("Erreur de chargement de la page.")
