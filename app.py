import streamlit as st
import os
import json
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
import subprocess
import sys
import time

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Scraper AI - Gemini", page_icon="🛒", layout="wide")

# --- INSTALLATION AUTOMATIQUE DU NAVIGATEUR ---
@st.cache_resource
def ensure_playwright_browsers():
    try:
        # Installation silencieuse de Chromium
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Note sur l'installation : {e}")

ensure_playwright_browsers()

# --- INITIALISATION GEMINI ---
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    st.error("⚠️ GEMINI_API_KEY manquante dans les Secrets de Streamlit.")

class SmartScraper:
    def fetch_page(self, url):
        # Utilisation de la version SYNCHRONE pour éviter les erreurs de boucle asyncio
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Scroll pour charger le contenu dynamique
                page.mouse.wheel(0, 2000)
                time.sleep(4)
                
                content = page.content()
                browser.close()
                return content
            except Exception as e:
                st.error(f"Erreur de chargement : {e}")
                return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        for s in soup(["script", "style", "nav", "footer", "header", "svg", "path", "iframe"]):
            s.decompose()
        # On garde les attributs importants pour l'EAN et les images
        return soup.prettify()[:45000]

    def extract_with_gemini(self, html_content):
        prompt = f"""
        Tu es un expert en Retail Arbitrage. Analyse ce HTML et extrais TOUS les produits visibles.
        Pour chaque produit, fournis : Nom, Prix, Marque, Code EAN (GTIN), URL Image, URL Produit.
        Si l'EAN n'est pas visible, cherche dans les attributs 'data-ean' ou 'gtin'.
        
        Réponds UNIQUEMENT avec un tableau JSON valide.
        HTML: {html_content}
        """
        try:
            response = model.generate_content(prompt)
            res_text = response.text
            if "```json" in res_text:
                res_text = res_text.split("```json")[1].split("```")[0]
            return json.loads(res_text)
        except Exception as e:
            st.error(f"Erreur IA : {e}")
            return []

# --- INTERFACE ---
st.title("🛒 Smart Scraper AI (Gemini)")
st.markdown("### Outil de détection autonome pour le Retail Arbitrage")

url_input = st.text_input("Entrez l'URL du listing (Lidl, Fnac, Carrefour, etc.)")

if st.button("Lancer l'extraction", type="primary"):
    if not api_key:
        st.warning("Configurez GEMINI_API_KEY dans les Secrets.")
    elif not url_input:
        st.warning("Entrez une URL.")
    else:
        scraper = SmartScraper()
        with st.status("Extraction en cours...", expanded=True) as status:
            st.write("🌐 Ouverture du navigateur et chargement de la page...")
            html = scraper.fetch_page(url_input)
            
            if html:
                st.write("🧠 Analyse des données par Gemini 1.5 Flash...")
                clean_html = scraper.clean_html(html)
                products = scraper.extract_with_gemini(clean_html)
                
                if products:
                    status.update(label="Extraction terminée !", state="complete")
                    df = pd.DataFrame(products)
                    st.subheader(f"📦 {len(products)} Produits détectés")
                    st.dataframe(df, use_container_width=True)
                    
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Télécharger CSV", csv, "arbitrage_data.csv", "text/csv")
                else:
                    status.update(label="Aucun produit trouvé.", state="error")
            else:
                status.update(label="Échec du chargement.", state="error")
