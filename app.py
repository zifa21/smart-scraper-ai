import streamlit as st
import os
import json
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from openai import OpenAI
import requests
from datetime import datetime

# Configuration de la page
st.set_page_config(page_title="Smart Scraper AI", page_icon="🛒", layout="wide")

# Installation de Playwright si nécessaire (pour le déploiement Cloud)
@st.cache_resource
def install_playwright():
    import os
    os.system("playwright install chromium")
    os.system("playwright install-deps")

install_playwright()

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
                json_ld = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                                .map(s => s.innerText);
                }""")
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
        context = f"Site: {url}\nType: {site_type}\n"
        if json_ld:
            context += f"JSON-LD: {json.dumps(json_ld)[:5000]}\n"

        prompt = f"""
        {context}
        Extraie les produits de cet HTML. Pour chaque produit:
        - name: Nom
        - price: Prix
        - ean: Code EAN/GTIN (cherche bien dans les attributs data-ean ou itemprop)
        - image_url: URL image
        - product_url: Lien
        - brand: Marque
        - source: Enseigne (Lidl, Carrefour, Fnac, etc.)

        Réponds UNIQUEMENT avec un objet JSON: {{"products": [...]}}
        """
        try:
            response = client.chat.completions.create(
                model="gemini-2.5-flash",
                messages=[
                    {"role": "system", "content": "Tu es un extracteur de données e-commerce précis."},
                    {"role": "user", "content": prompt + "\n\nHTML:\n" + html_snippet}
                ],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except:
            return None

    async def run_scraping(self, url, deep_scan=False):
        with st.status(f"Analyse de {url}...", expanded=True) as status:
            st.write("🌐 Chargement de la page...")
            res = await self.detect_and_fetch(url)
            if not res:
                status.update(label="❌ Erreur de chargement", state="error")
                return None
            
            st.write(f"🧠 Extraction IA ({res['type']})...")
            cleaned = self.clean_html(res['html'])
            data = await self.analyze_with_ai(cleaned, res['json_ld'], url, res['type'])
            
            if data and 'products' in data:
                products = data['products']
                st.write(f"✅ {len(products)} produits trouvés.")
                
                if deep_scan:
                    st.write("🔍 Scan approfondi pour les codes EAN...")
                    for i, p in enumerate(products):
                        if not p.get('ean') and p.get('product_url'):
                            st.write(f"  ↳ Analyse de : {p['name'][:30]}...")
                            p_res = await self.detect_and_fetch(p['product_url'])
                            if p_res:
                                p_data = await self.analyze_with_ai(self.clean_html(p_res['html']), p_res['json_ld'], p['product_url'], p_res['type'])
                                if p_data and 'products' in p_data:
                                    details = p_data['products'][0] if p_data['products'] else {}
                                    p.update({k: v for k, v in details.items() if v})
                
                for p in products:
                    p['source_url'] = url
                
                self.save_to_history(products)
                status.update(label="✨ Scraping terminé !", state="complete")
                return products
            else:
                status.update(label="⚠️ Aucun produit trouvé", state="error")
                return None

# --- INTERFACE STREAMLIT ---

st.title("🛒 Smart Scraper AI")
st.markdown("Outil autonome pour le **Retail Arbitrage**. Détecte la structure, extrait les EAN et les images via IA.")

scraper = SmartScraper()

with st.sidebar:
    st.header("Configuration")
    deep_scan = st.checkbox("Scan approfondi (EAN)", value=True, help="Visite chaque page produit pour trouver le code EAN s'il est absent du listing.")
    
    if st.button("Effacer l'historique"):
        if os.path.exists("scraping_history.json"):
            os.remove("scraping_history.json")
        st.session_state.history = []
        st.rerun()

url_input = st.text_input("Entrez l'URL du site (Lidl, Carrefour, Fnac, etc.) :", placeholder="https://www.fnac.com/...")

if st.button("Lancer le Scraping", type="primary"):
    if url_input:
        results = asyncio.run(scraper.run_scraping(url_input, deep_scan))
        if results:
            st.balloons()
    else:
        st.warning("Veuillez entrer une URL.")

# Affichage des résultats
if st.session_state.history:
    st.divider()
    df = pd.DataFrame(st.session_state.history)
    
    # Réorganiser les colonnes
    cols = ['name', 'price', 'ean', 'brand', 'source', 'image_url', 'product_url', 'timestamp']
    df = df[[c for c in cols if c in df.columns]]
    
    st.subheader(f"📊 Données extraites ({len(df)} produits)")
    
    # Affichage avec images
    st.dataframe(
        df,
        column_config={
            "image_url": st.column_config.ImageColumn("Image"),
            "product_url": st.column_config.LinkColumn("Lien Produit"),
            "ean": st.column_config.TextColumn("Code EAN", help="Code barre unique du produit")
        },
        hide_index=True,
        use_container_width=True
    )
    
    # Boutons d'export
    col1, col2 = st.columns(2)
    with col1:
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Télécharger en CSV", data=csv, file_name="produits_arbitrage.csv", mime="text/csv")
    with col2:
        json_data = json.dumps(st.session_state.history, indent=4).encode('utf-8')
        st.download_button("📥 Télécharger en JSON", data=json_data, file_name="produits_arbitrage.json", mime="application/json")
else:
    st.info("L'historique est vide. Entrez une URL pour commencer.")
