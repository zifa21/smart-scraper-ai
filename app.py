import streamlit as st
import os
import json
import pandas as pd
from bs4 import BeautifulSoup
import requests
import time
import re

# --- CONFIGURATION ---
st.set_page_config(page_title="Smart Scraper AI - Groq", page_icon="🛒", layout="wide")

# API Key Groq (gratuit)
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY") if hasattr(st, 'secrets') else os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error("⚠️ GROQ_API_KEY manquante")
    st.info("""
    ### 🆓 Obtenir une clé API Groq GRATUITE :
    1. Allez sur https://console.groq.com
    2. Créez un compte (gratuit)
    3. Allez dans 'API Keys'
    4. Créez une clé
    5. Ajoutez dans Secrets: `GROQ_API_KEY = "gsk_..."`
    
    **Groq est VRAIMENT gratuit et ultra-rapide !**
    """)
    st.stop()

class SmartScraper:
    def __init__(self):
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
    
    def call_ai(self, prompt):
        """Appelle Groq AI"""
        payload = {
            "model": "llama-3.3-70b-versatile",  # Modèle gratuit et puissant
            "messages": [
                {"role": "system", "content": "Tu es un expert en extraction de données e-commerce. Réponds UNIQUEMENT en JSON valide."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 8000
        }
        
        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            return response.json()['choices'][0]['message']['content']
        except Exception as e:
            st.error(f"❌ Erreur API: {str(e)}")
            return None
    
    def fetch_page(self, url):
        """Récupère la page web"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            st.error(f"❌ Erreur connexion: {str(e)}")
            return None

    def clean_html(self, html, url):
        """Nettoie le HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        
        for tag in soup(["script", "style", "nav", "footer", "header", "svg"]):
            tag.decompose()
        
        domain = '/'.join(url.split('/')[:3])
        products = []
        
        # Cherche les conteneurs produits
        for container in soup.find_all(['div', 'article'], class_=re.compile(r'product|item|card', re.I))[:20]:
            text = container.get_text(separator=' ', strip=True)[:500]
            images = [img.get('src', '') for img in container.find_all('img')]
            links = [a.get('href', '') for a in container.find_all('a')]
            
            products.append({
                'text': text,
                'images': [domain + img if img.startswith('/') else img for img in images[:2]],
                'links': [domain + link if link.startswith('/') else link for link in links[:2]]
            })
        
        return products

    def extract_products(self, content_parts, url):
        """Extraction avec IA"""
        formatted = "PRODUITS:\n\n"
        for i, part in enumerate(content_parts[:10], 1):
            formatted += f"--- PRODUIT {i} ---\n{part['text']}\n"
            if part['images']: formatted += f"Image: {part['images'][0]}\n"
            if part['links']: formatted += f"URL: {part['links'][0]}\n\n"
        
        prompt = f"""Extrais les produits de ce contenu e-commerce.

Retourne un JSON array avec pour chaque produit:
{{"nom": "...", "prix": "XX.XX", "marque": "..." or null, "ean": "..." or null, "image_url": "..." or null, "product_url": "..." or null}}

RÈGLES:
- Retourne UNIQUEMENT le JSON array
- Commence par [ et termine par ]
- Prix en format "XX.XX"

CONTENU:
{formatted}"""

        result = self.call_ai(prompt)
        if not result:
            return []
        
        try:
            # Nettoie la réponse
            result = result.strip()
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            
            json_match = re.search(r'\[.*\]', result, re.DOTALL)
            if json_match:
                result = json_match.group(0)
            
            products = json.loads(result)
            return products if isinstance(products, list) else [products]
        except:
            st.error("❌ Erreur parsing JSON")
            return []

# --- INTERFACE ---
st.title("🛒 Smart Scraper AI - Groq (Ultra-Rapide)")
st.markdown("### Extraction gratuite et illimitée")

if GROQ_API_KEY:
    st.success("✅ API Groq connectée - Prêt à extraire !")

url = st.text_input("🔗 URL du site", placeholder="https://www.exemple.com/produits")

if st.button("🚀 Extraire les produits", type="primary"):
    if not url:
        st.warning("⚠️ Entrez une URL")
    else:
        scraper = SmartScraper()
        
        with st.status("Extraction...", expanded=True) as status:
            st.write("🌐 Récupération...")
            html = scraper.fetch_page(url)
            
            if html:
                st.write("🧹 Analyse HTML...")
                parts = scraper.clean_html(html, url)
                st.write(f"✅ {len(parts)} sections trouvées")
                
                st.write("🤖 Extraction IA...")
                products = scraper.extract_products(parts, url)
                
                if products:
                    status.update(label=f"✅ {len(products)} produits extraits", state="complete")
                    
                    df = pd.DataFrame(products)
                    st.dataframe(df, use_container_width=True)
                    
                    csv = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                    st.download_button("📥 CSV", csv, f"products_{time.time()}.csv", "text/csv")
                else:
                    st.warning("Aucun produit trouvé")
            else:
                status.update(label="❌ Échec", state="error")

st.markdown("---")
st.caption("💡 Propulsé par Groq - Gratuit et sans limite !")
