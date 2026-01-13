import subprocess
import sys
import os

# --- INSTALLATION AUTOMATIQUE DES DÉPENDANCES ---
def install_dependencies():
    dependencies = ["google-generativeai", "playwright", "beautifulsoup4", "pandas", "requests"]
    for lib in dependencies:
        try:
            __import__(lib.replace("-", "_"))
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])
    
    # Installation spécifique des navigateurs Playwright
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    except Exception as e:
        print(f"Note: Playwright browser install: {e}")

install_dependencies()

# --- IMPORT DES BIBLIOTHÈQUES ---
import streamlit as st
import json
import asyncio
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import requests
from datetime import datetime

# --- CONFIGURATION ---
st.set_page_config(page_title="Smart Scraper AI - Gemini Edition", page_icon="🛒", layout="wide")

# Initialisation de Gemini
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash') # Version stable et gratuite
else:
    st.error("⚠️ GEMINI_API_KEY manquante dans les Secrets de Streamlit.")

class SmartScraper:
    async def fetch_page(self, url):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                # Petit scroll pour charger le contenu dynamique
                await page.mouse.wheel(0, 1000)
                await asyncio.sleep(2)
                content = await page.content()
                await browser.close()
                return content
            except Exception as e:
                await browser.close()
                st.error(f"Erreur de navigation: {e}")
                return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        # On garde l'essentiel pour l'IA
        for s in soup(["script", "style", "nav", "footer", "header", "svg"]):
            s.decompose()
        return soup.prettify()[:30000]

    async def extract_with_gemini(self, html_content):
        prompt = f"""
        Tu es un expert en Retail Arbitrage. Analyse ce HTML et extrais la liste des produits.
        Pour chaque produit, trouve : Nom, Prix, Marque, Code EAN (GTIN), URL Image, URL Produit.
        
        HTML: {html_content}
        
        Réponds UNIQUEMENT avec un tableau JSON valide.
        """
        try:
            response = model.generate_content(prompt)
            res_text = response.text
            # Nettoyage du format markdown si présent
            if "```json" in res_text:
                res_text = res_text.split("```json")[1].split("```")[0]
            return json.loads(res_text)
        except Exception as e:
            st.error(f"Erreur IA Gemini: {e}")
            return []

# --- INTERFACE UTILISATEUR ---
st.title("🛒 Smart Scraper AI (Gemini 1.5 Flash)")
st.info("Outil autonome pour le Retail Arbitrage - Détection intelligente de produits.")

url_input = st.text_input("Collez l'URL du site (Lidl, Fnac, Carrefour, etc.)", placeholder="https://www.example.com/produits")

if st.button("Lancer l'extraction", type="primary"):
    if not api_key:
        st.warning("Veuillez configurer votre GEMINI_API_KEY dans Streamlit Cloud.")
    elif not url_input:
        st.warning("Veuillez entrer une URL valide.")
    else:
        scraper = SmartScraper()
        with st.status("Extraction en cours...", expanded=True) as status:
            st.write("🌐 Chargement de la page (Playwright)...")
            html = asyncio.run(scraper.fetch_page(url_input))
            
            if html:
                st.write("🧠 Analyse intelligente par Gemini...")
                clean_html = scraper.clean_html(html)
                products = asyncio.run(scraper.extract_with_gemini(clean_html))
                
                if products:
                    status.update(label="Extraction réussie !", state="complete")
                    df = pd.DataFrame(products)
                    st.subheader(f"📦 {len(products)} Produits détectés")
                    st.dataframe(df, use_container_width=True)
                    
                    # Export
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Télécharger les données (CSV)", csv, "extract_arbitrage.csv", "text/csv")
                else:
                    status.update(label="Aucun produit trouvé.", state="error")
            else:
                status.update(label="Échec du chargement de la page.", state="error")
