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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                for _ in range(2):
                    await page.mouse.wheel(0, 800)
                    await asyncio.sleep(1)
                content = await page.content()
                json_ld = await page.evaluate(\"\"\"() => {
                    return Array.from(document.querySelectorAll('script[type=\"application/ld+json\"]'))
                        .map(s => s.innerText);
                }\"\"\")
                await browser.close()
                return {"type": "Statique" if is_static else "Dynamique", "html": content, "json_ld": json_ld}
            except Exception as e:
                await browser.close()
                return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        for s in soup(["script", "style", "svg", "path", "footer", "nav", "header"]):
            s.decompose()
        for tag in soup.find_all(True):
            allowed_attrs = ['class', 'id', 'href', 'src', 'data-ean', 'data-gtin', 'itemprop', 'content']
            attrs = dict(tag.attrs)
            tag.attrs = {k: v for k, v in attrs.items() if k in allowed_attrs}
        return soup.prettify()[:30000]

    async def analyze_with_ai(self, html_snippet, json_ld, url, site_type):
        context = f"Site: {url}\\nType: {site_type}\\n"
        if json_ld:
            context += f"JSON-LD: {json_ld[:5000]}\\n"
        
        prompt = f\"\"\"
        Tu es un expert en extraction de données e-commerce. Analyse ce code HTML et JSON-LD pour extraire les produits.
        {context}
        HTML: {html_snippet}
        
        Retourne UNIQUEMENT un JSON valide (liste d'objets) avec:
        - name: nom du produit
        - price: prix (nombre ou texte)
        - brand: marque (si dispo)
        - ean: code EAN/GTIN (TRÈS IMPORTANT, cherche partout)
        - image_url: lien de l'image principale
        - product_url: lien vers la page produit (si relatif, garde le tel quel)
        \"\"\"
        
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            return data.get('products', data) if isinstance(data, dict) else data
        except Exception as e:
            st.error(f"Erreur IA: {e}")
            return []

    async def get_deep_ean(self, product_url, base_url):
        if not product_url.startswith('http'):
            from urllib.parse import urljoin
            product_url = urljoin(base_url, product_url)
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(product_url, wait_until=\"networkidle\", timeout=30000)
                content = await page.content()
                await browser.close()
                
                prompt = f\"Extrais UNIQUEMENT le code EAN/GTIN de ce HTML. Si non trouvé, réponds 'null'. HTML: {content[:20000]}\"
                response = client.chat.completions.create(
                    model=\"gpt-4.1-mini\",
                    messages=[{\"role\": \"user\", \"content\": prompt}]
                )
                ean = response.choices[0].message.content.strip()
                return ean if ean.lower() != 'null' else None
            except:
                await browser.close()
                return None

# Interface Streamlit
st.title(\"🚀 Smart Scraper AI - Retail Arbitrage\")
st.markdown(\"Outil autonome pour détecter et extraire les produits avec EAN.\")

with st.sidebar:
    st.header(\"Paramètres\")
    deep_scan = st.checkbox(\"Scan approfondi (visite chaque page pour l'EAN)\", value=False)
    if st.button(\"Effacer l'historique\"):
        if os.path.exists(\"scraping_history.json\"):
            os.remove(\"scraping_history.json\")
        st.session_state.history = []
        st.rerun()

url_input = st.text_input(\"Entrez l'URL du listing (ex: Lidl, Fnac, Carrefour...)\", placeholder=\"https://www.lidl.fr/c/cuisiner/c158\")

if st.button(\"Lancer le Scraping\", type=\"primary\"):
    if not url_input:
        st.warning(\"Veuillez entrer une URL.\")
    else:
        scraper = SmartScraper()
        with st.status(\"Analyse du site en cours...\", expanded=True) as status:
            st.write(\"Détection de la structure...\")
            site_data = asyncio.run(scraper.detect_and_fetch(url_input))
            
            if site_data:
                st.write(f\"Type détecté: **{site_data['type']}**\")
                st.write(\"Extraction des données par l'IA...\")
                clean_html = scraper.clean_html(site_data['html'])
                products = asyncio.run(scraper.analyze_with_ai(clean_html, site_data['json_ld'], url_input, site_data['type']))
                
                if products:
                    st.write(f\"✅ {len(products)} produits trouvés.\")
                    
                    if deep_scan:
                        st.write(\"🔍 Lancement du scan approfondi pour les EAN...\")
                        progress_bar = st.progress(0)
                        for i, p in enumerate(products):
                            if not p.get('ean') and p.get('product_url'):
                                ean = asyncio.run(scraper.get_deep_ean(p['product_url'], url_input))
                                if ean:
                                    p['ean'] = ean
                            progress_bar.progress((i + 1) / len(products))
                    
                    scraper.save_to_history(products)
                    status.update(label=\"Scraping terminé !\", state=\"complete\", expanded=False)
                    
                    st.subheader(\"Résultats\")
                    df = pd.DataFrame(products)
                    st.dataframe(df, use_container_width=True)
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(\"Télécharger CSV\", df.to_csv(index=False), \"products.csv\", \"text/csv\")
                    with col2:
                        st.download_button(\"Télécharger JSON\", df.to_json(orient=\"records\"), \"products.json\", \"application/json\")
                else:
                    st.error(\"Aucun produit trouvé. L'IA n'a pas pu identifier de listing.\")
            else:
                st.error(\"Impossible d'accéder au site.\")

st.divider()
st.subheader(\"📜 Historique Global\")
if st.session_state.get('history'):
    history_df = pd.DataFrame(st.session_state.history)
    st.dataframe(history_df, use_container_width=True)
else:
    st.info(\"L'historique est vide.\")
