import streamlit as st
import os
import json
import asyncio
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import subprocess
import sys

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Scraper AI - Gemini", page_icon="🛒", layout="wide")

# --- INSTALLATION AUTOMATIQUE DU NAVIGATEUR ---
@st.cache_resource
def ensure_playwright_browsers():
    # Cette fonction installe Chromium si nécessaire au premier lancement
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        st.error(f"Erreur lors de l'installation du navigateur : {e}")

ensure_playwright_browsers()

# --- INITIALISATION GEMINI ---
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    st.error("⚠️ GEMINI_API_KEY manquante dans les Secrets de Streamlit.")

class SmartScraper:
    async def fetch_page(self, url):
        async with async_playwright() as p:
            try:
                # Lancement du navigateur avec des options de stabilité
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Petit scroll pour déclencher le chargement des images/produits
                await page.mouse.wheel(0, 1000)
                await asyncio.sleep(3)
                
                content = await page.content()
                await browser.close()
                return content
            except Exception as e:
                st.error(f"Erreur lors du chargement de la page : {e}")
                return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        # On retire le superflu pour ne pas saturer l'IA
        for s in soup(["script", "style", "nav", "footer", "header", "svg", "path"]):
            s.decompose()
        # On limite la taille pour rester dans les limites de Gemini
        return soup.prettify()[:40000]

    async def extract_with_gemini(self, html_content):
        prompt = f"""
        Analyse ce code HTML e-commerce et extrais la liste des produits.
        Pour chaque produit, trouve : Nom, Prix, Marque, Code EAN (GTIN), URL Image, URL Produit.
        Réponds UNIQUEMENT avec un tableau JSON valide.
        
        HTML: {html_content}
        """
        try:
            response = model.generate_content(prompt)
            res_text = response.text
            # Nettoyage du formatage Markdown si présent
            if "```json" in res_text:
                res_text = res_text.split("```json")[1].split("```")[0]
            return json.loads(res_text)
        except Exception as e:
            st.error(f"Erreur d'analyse IA : {e}")
            return []

# --- INTERFACE UTILISATEUR ---
st.title("🛒 Smart Scraper AI (Gemini)")
st.markdown("Outil autonome pour le Retail Arbitrage.")

url_input = st.text_input("Entrez l'URL du listing produit (ex: Lidl, Fnac, etc.)")

if st.button("Lancer l'extraction", type="primary"):
    if not api_key:
        st.warning("Veuillez configurer votre GEMINI_API_KEY.")
    elif not url_input:
        st.warning("Veuillez entrer une URL.")
    else:
        scraper = SmartScraper()
        with st.status("Traitement en cours...", expanded=True) as status:
            st.write("🌐 Chargement de la page...")
            html = asyncio.run(scraper.fetch_page(url_input))
            
            if html:
                st.write("🧠 Analyse intelligente par Gemini...")
                clean_html = scraper.clean_html(html)
                products = asyncio.run(scraper.extract_with_gemini(clean_html))
                
                if products:
                    status.update(label="Extraction terminée !", state="complete")
                    df = pd.DataFrame(products)
                    st.subheader(f"📦 {len(products)} Produits trouvés")
                    st.dataframe(df, use_container_width=True)
                    
                    # Bouton de téléchargement
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Télécharger les données (CSV)", csv, "extraction_produits.csv", "text/csv")
                else:
                    status.update(label="Aucun produit détecté par l'IA.", state="error")
            else:
                status.update(label="Impossible de charger la page.", state="error")
