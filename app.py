import streamlit as st
import os
import json
import pandas as pd
import google.generativeai as genai
from bs4 import BeautifulSoup
import requests
import time

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Scraper AI - Gemini", page_icon="🛒", layout="wide")

# --- INITIALISATION GEMINI ---
api_key = st.secrets.get("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    st.error("⚠️ GEMINI_API_KEY manquante dans les Secrets de Streamlit.")

class SmartScraper:
    def fetch_page(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
        try:
            # On utilise une session pour gérer les cookies
            session = requests.Session()
            response = session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            st.error(f"Erreur de connexion au site : {e}")
            return None

    def clean_html(self, html):
        soup = BeautifulSoup(html, 'html.parser')
        # On supprime tout ce qui n'est pas du contenu produit
        for s in soup(["script", "style", "nav", "footer", "header", "svg", "path", "iframe", "aside"]):
            s.decompose()
        
        # On extrait les balises qui contiennent potentiellement des infos produits
        important_tags = soup.find_all(['div', 'span', 'a', 'img', 'h1', 'h2', 'h3', 'li'])
        
        # On reconstruit un HTML ultra-léger pour Gemini
        mini_html = ""
        for tag in important_tags:
            if tag.name == 'img' and tag.get('src'):
                mini_html += f'<img src="{tag.get("src")}"> '
            elif tag.text.strip():
                # On garde les attributs qui contiennent souvent l'EAN
                ean_info = ""
                for attr in ['data-ean', 'data-gtin', 'itemprop', 'content']:
                    if tag.get(attr):
                        ean_info += f' {attr}="{tag.get(attr)}"'
                mini_html += f'<{tag.name}{ean_info}>{tag.text.strip()[:200]}</{tag.name}> '
        
        return mini_html[:50000] # On donne un maximum de contexte à Gemini

    def extract_with_gemini(self, html_content, url):
        prompt = f"""
        Tu es un expert en Retail Arbitrage. Analyse ce contenu HTML provenant de {url} et extrais TOUS les produits.
        Pour chaque produit, trouve : Nom, Prix, Marque, Code EAN (GTIN), URL Image, URL Produit.
        
        IMPORTANT : 
        1. Si l'EAN n'est pas explicite, cherche dans les attributs ou les descriptions.
        2. Si les URLs sont relatives, complète-les avec le domaine du site.
        3. Réponds UNIQUEMENT avec un tableau JSON valide.
        
        CONTENU : {html_content}
        """
        try:
            response = model.generate_content(prompt)
            res_text = response.text
            if "```json" in res_text:
                res_text = res_text.split("```json")[1].split("```")[0]
            return json.loads(res_text)
        except Exception as e:
            st.error(f"Erreur d'analyse IA : {e}")
            return []

# --- INTERFACE ---
st.title("🛒 Smart Scraper AI (Gemini Ultra-Light)")
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
            st.write("🌐 Récupération du contenu du site...")
            html = scraper.fetch_page(url_input)
            
            if html:
                st.write("🧠 Analyse intelligente par Gemini 1.5 Flash...")
                clean_html = scraper.clean_html(html)
                products = scraper.extract_with_gemini(clean_html, url_input)
                
                if products:
                    status.update(label="Extraction terminée !", state="complete")
                    df = pd.DataFrame(products)
                    st.subheader(f"📦 {len(products)} Produits détectés")
                    st.dataframe(df, use_container_width=True)
                    
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button("📥 Télécharger CSV", csv, "arbitrage_data.csv", "text/csv")
                else:
                    status.update(label="Aucun produit trouvé. Le site bloque peut-être les requêtes directes.", state="error")
            else:
                status.update(label="Échec de la récupération.", state="error")
